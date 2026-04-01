# Infraestructura de Producción — Ecofilia RAGv2

**Región:** us-east-2 (Ohio)
**Cuenta AWS:** 028780196116
**Dominio:** ecofilia.site
**Fecha de último update:** 2026-03-30

---

## Índice

1. [Diagrama general](#1-diagrama-general)
2. [Red — VPC y subnets](#2-red--vpc-y-subnets)
3. [Seguridad — Security Groups](#3-seguridad--security-groups)
4. [Acceso público — ALB](#4-acceso-público--alb)
5. [Cómputo — ECS Fargate](#5-cómputo--ecs-fargate)
6. [Base de datos — RDS PostgreSQL](#6-base-de-datos--rds-postgresql)
7. [Cola de mensajes — SQS](#7-cola-de-mensajes--sqs)
8. [Imágenes Docker — ECR](#8-imágenes-docker--ecr)
9. [Secretos — Secrets Manager](#9-secretos--secrets-manager)
10. [Observabilidad — CloudWatch](#10-observabilidad--cloudwatch)
11. [CI/CD — GitHub Actions](#11-cicd--github-actions)
12. [DNS](#12-dns)
13. [Auto Scaling](#13-auto-scaling)
14. [Costos estimados](#14-costos-estimados)

---

## 1. Diagrama general

```
Internet
    │
    ▼
[Vercel DNS]  →  api.ecofilia.site  (CNAME → ecofilia-alb)
                                         │
                              ┌──────────▼──────────┐
                              │   ALB ecofilia-alb   │
                              │  HTTP:80 → redirect  │
                              │  HTTPS:443 → forward │
                              │  Cert: ACM (*.site)  │
                              └──────────┬──────────┘
                                         │ (puerto 8000)
                              ┌──────────▼──────────┐
                              │    VPC 10.0.0.0/16   │
                              │                      │
                              │  ┌─────────────────┐ │
                              │  │  ECS API (×2)   │ │  ← On-Demand
                              │  │  Django/gunicorn │ │
                              │  └────────┬────────┘ │
                              │           │           │
                              │  ┌────────▼────────┐ │
                              │  │  ECS Worker (×1)│ │  ← Fargate Spot
                              │  │  Celery worker  │ │
                              │  └────────┬────────┘ │
                              │           │           │
                              │  ┌────────▼────────┐ │
                              │  │  ECS Beat (×1)  │ │  ← Fargate Spot
                              │  │  Celery beat    │ │
                              │  └─────────────────┘ │
                              │           │           │
                              │  ┌────────▼────────┐ │
                              │  │  RDS PostgreSQL  │ │
                              │  │  db.t4g.micro   │ │
                              │  │  + pgvector     │ │
                              │  └─────────────────┘ │
                              │                      │
                              │  [NAT Gateway] ──────┼──► AWS APIs
                              └──────────────────────┘    (OpenAI, ECR,
                                                           SQS, S3,
                                                           Secrets Manager)
```

---

## 2. Red — VPC y subnets

**VPC:** `vpc-016d5a3f84efb5f97`
**CIDR:** `10.0.0.0/16`
**NAT Gateway:** `nat-08e76c4220fa768d7` (en subred pública 2a)

### Subnets públicas (ALB)

| Nombre | ID | AZ | CIDR |
|--------|----|----|------|
| ecofilia-public-2a | subnet-01510c6d63a0b283a | us-east-2a | 10.0.1.0/24 |
| ecofilia-public-2b | subnet-036b73508f0558fe4 | us-east-2b | 10.0.2.0/24 |
| ecofilia-public-2c | subnet-0de217f9f63e9704d | us-east-2c | 10.0.3.0/24 |

Solo el ALB vive aquí. Tienen Internet Gateway directo.

### Subnets privadas — ECS

| Nombre | ID | AZ | CIDR |
|--------|----|----|------|
| ecofilia-private-ecs-2a | subnet-0eeb7c030c003896d | us-east-2a | 10.0.10.0/24 |
| ecofilia-private-ecs-2b | subnet-084c6ea560cf05512 | us-east-2b | 10.0.11.0/24 |
| ecofilia-private-ecs-2c | subnet-0bf0864eb1124711d | us-east-2c | 10.0.12.0/24 |

Los tres servicios ECS (API, Worker, Beat) corren aquí. Sin IP pública. Salen al exterior a través del NAT Gateway (para llamadas a OpenAI, ECR, SQS, etc.).

### Subnets privadas — RDS

| Nombre | ID | AZ | CIDR |
|--------|----|----|------|
| ecofilia-private-rds-2a | subnet-0b3e00035148837fe | us-east-2a | 10.0.20.0/24 |
| ecofilia-private-rds-2b | subnet-08ef795bc55db10d3 | us-east-2b | 10.0.21.0/24 |
| ecofilia-private-rds-2c | subnet-0faea859a96833f95 | us-east-2c | 10.0.22.0/24 |

La base de datos vive aquí. No tiene acceso público. Solo es alcanzable desde los servicios ECS dentro de la VPC.

---

## 3. Seguridad — Security Groups

### `ecofilia-sg-alb` (`sg-049b3db6f9b45feb1`)
**Quién:** ALB
**Entrada:** TCP 80 y 443 desde `0.0.0.0/0` (internet)
**Salida:** TCP 8000 hacia `ecofilia-sg-ecs-api`

### `ecofilia-sg-ecs-api` (`sg-0e751d4a7ed56c286`)
**Quién:** Tareas ECS del servicio API
**Entrada:** TCP 8000 desde `ecofilia-sg-alb` solamente
**Salida:** TCP 5432 hacia `ecofilia-sg-rds`, TCP 443 hacia internet (Secrets Manager, ECR, OpenAI)

### `ecofilia-sg-ecs-worker` (`sg-060d35df0ec63c774`)
**Quién:** Tareas ECS del servicio Worker
**Entrada:** ninguna
**Salida:** TCP 5432 hacia `ecofilia-sg-rds`, TCP 443 hacia internet (OpenAI, SQS, S3)

### `ecofilia-sg-ecs-beat` (`sg-0787290e7c847a49d`)
**Quién:** Tareas ECS del servicio Beat
**Entrada:** ninguna
**Salida:** TCP 5432 hacia `ecofilia-sg-rds`, TCP 443 hacia internet (SQS)

### `ecofilia-sg-rds` (`sg-0748a16a26bf7c2c3`)
**Quién:** Instancia RDS
**Entrada:** TCP 5432 desde `ecofilia-sg-ecs-api`, `ecofilia-sg-ecs-worker`, `ecofilia-sg-ecs-beat`
**Salida:** ninguna relevante

> Ningún recurso tiene acceso público directo excepto el ALB. La RDS no es accesible desde internet.

---

## 4. Acceso público — ALB

**Nombre:** `ecofilia-alb`
**ARN:** `arn:aws:elasticloadbalancing:us-east-2:028780196116:loadbalancer/app/ecofilia-alb/182d5582dd6c2d41`
**DNS propio:** `ecofilia-alb-2056124034.us-east-2.elb.amazonaws.com`
**Subnets:** las 3 públicas (multi-AZ)

### Listeners

| Puerto | Protocolo | Acción |
|--------|-----------|--------|
| 80 | HTTP | Redirect 301 → HTTPS |
| 443 | HTTPS | Forward → `ecofilia-tg-api` |

**Certificado SSL:** ACM, `api.ecofilia.site` — TLS 1.2/1.3

### Target Group `ecofilia-tg-api`
- **Tipo:** IP (requerido para Fargate awsvpc)
- **Puerto:** 8000
- **Health check:** `GET /health/` — espera HTTP 200
- **Targets actuales:** 2 IPs privadas (las 2 tareas del API)

### Health check especial
El ALB hace health checks con la IP privada del task como `Host` header, lo cual Django rechazaría normalmente. La app tiene un `HealthCheckMiddleware` que intercepta `/health/` **antes** de que Django valide el `ALLOWED_HOSTS`, evitando el error 400.

---

## 5. Cómputo — ECS Fargate

**Cluster:** `cluster-ecofilia`

### Servicio: `ecofilia-api`

| Campo | Valor |
|-------|-------|
| Task definition | `ecofilia-api:6` |
| CPU / Memoria | 512 vCPU units / 1024 MB |
| Tareas deseadas | 2 |
| Capacity provider | On-Demand (FARGATE) |
| Auto Scaling | mín 2 — máx 6 (CPU 60%, Memory 70%) |
| Subnets | private-ecs-2a/2b/2c |
| Security Group | ecofilia-sg-ecs-api |

**Qué hace:** Sirve la API REST de Django con Gunicorn (2 workers). Maneja autenticación JWT, queries a la DB, búsquedas vectoriales con pgvector, y encola tareas asíncronas en SQS.

**Comando:** `gunicorn main.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120`

**Variables de entorno relevantes:**
```
DJANGO_SETTINGS_MODULE=main.settings.prod
DEBUG=False
ALLOWED_HOSTS=api.ecofilia.site
POSTGRES_SSLMODE=require
SECURE_HSTS_SECONDS=31536000
MODEL_COMPLETION=gpt-4o-mini
MODEL_EMBEDDING=text-embedding-3-small
SQS_QUEUE_URL=https://sqs.us-east-2.amazonaws.com/028780196116/ecofilia-celery-sqs
```

---

### Servicio: `ecofilia-worker`

| Campo | Valor |
|-------|-------|
| Task definition | `ecofilia-worker:4` |
| CPU / Memoria | 1024 vCPU units / 2048 MB |
| Tareas deseadas | 1 |
| Capacity provider | **FARGATE_SPOT** (4:1 fallback On-Demand) |
| Auto Scaling | mín 1 — máx 3 |
| Subnets | private-ecs-2a/2b/2c |
| Security Group | ecofilia-sg-ecs-worker |

**Qué hace:** Ejecuta las tareas asíncronas de Celery que consume de SQS. Tiene concurrencia de 2 (procesa 2 tareas en paralelo).

**Comando:** `celery -A main worker --loglevel=info --concurrency=2`

**Tareas que procesa:**

1. **`process_document_chunks`** — Disparada automáticamente cuando se sube un documento (señal `post_save`).
   - Descarga el archivo desde S3
   - Parsea PDF/DOCX/TXT (con PyMuPDF)
   - Divide en chunks de 500 tokens (overlap 50) usando tiktoken
   - Llama a OpenAI `text-embedding-3-small` para generar embeddings de 1536 dimensiones por chunk
   - Guarda los `SmartChunk` con sus vectores en PostgreSQL (pgvector)
   - Retries: 3 intentos, delay 30s entre cada uno

2. **`run_evaluation_task`** — Disparada por endpoint REST cuando se lanza una evaluación.
   - Itera sobre Pillares → Métricas del template de evaluación
   - Por cada métrica: RAG query con pgvector + llamada a `gpt-4o-mini`
   - Guarda resultados en la DB
   - Puede tardar varios minutos (10+ para evaluaciones grandes)

3. **`run_asg_evaluation_task`** — Evaluación con metodología Allen & Manza.
   - Similar a la anterior pero con prompt especializado para ASG
   - Actualmente comentada para ejecución async (corre sincrónicamente desde la vista)

**Nota sobre Spot:** Con `TASK_ACKS_LATE=True` y visibility timeout de 3600s en SQS, si AWS interrumpe el worker a mitad de tarea, SQS devuelve el mensaje a la cola y otro worker lo retoma automáticamente.

---

### Servicio: `ecofilia-beat`

| Campo | Valor |
|-------|-------|
| Task definition | `ecofilia-beat:5` |
| CPU / Memoria | 256 vCPU units / 512 MB |
| Tareas deseadas | 1 |
| Capacity provider | **FARGATE_SPOT** (4:1 fallback On-Demand) |
| Subnets | private-ecs-2a/2b/2c |
| Security Group | ecofilia-sg-ecs-beat |

**Qué hace:** Corre el scheduler de Celery Beat. Actualmente no tiene tareas periódicas configuradas (`CELERY_BEAT_SCHEDULE` vacío), pero el servicio está disponible para cuando se agreguen.

**Comando:** `celery -A main beat --loglevel=info`

---

### Docker image

Todos los servicios usan la misma imagen Docker, diferenciándose solo por el comando de arranque.

**Build (multi-stage):**
- Stage 1 (`builder`): instala dependencias de Python con Poetry
- Stage 2 (`production`): imagen mínima `python:3.12-slim`, usuario no-root `ecofilia`, `libpq5` para psycopg2
- `collectstatic` se corre en build time con credenciales placeholder
- Health check del contenedor: `curl http://localhost:8000/health/`

---

## 6. Base de datos — RDS PostgreSQL

| Campo | Valor |
|-------|-------|
| Identificador | `ecofilia-db` |
| Endpoint | `ecofilia-db.cjsem8ewibzq.us-east-2.rds.amazonaws.com` |
| Motor | PostgreSQL 17.4 |
| Instancia | `db.t4g.micro` (2 vCPU ARM, 1 GB RAM) |
| Storage | 20 GB gp3 |
| Multi-AZ | No |
| Acceso público | No |
| SSL | Requerido (`sslmode=require` en Django) |
| Subnet group | ecofilia-private-rds-2a/2b/2c |
| Security Group | ecofilia-sg-rds |

**Extensiones instaladas:**
- `pgvector` — almacenamiento y búsqueda de vectores de embeddings (1536 dimensiones)

**Base de datos:** `postgres` (usuario `postgres`)

**Apps de Django con tablas:**
`admin`, `auth`, `authtoken`, `chat`, `contenttypes`, `document`, `evaluation`, `otp_totp`, `project`, `sessions`, `sites`, `token_blacklist`, `user`

**Snapshots disponibles:**
- `ecofilia-migration-snapshot` — tomado antes de la migración (2026-03-30)
- `db-ecofilia-final-backup` — snapshot final de la DB vieja antes de eliminarla
- Backups automáticos diarios de AWS

---

## 7. Cola de mensajes — SQS

**Nombre:** `ecofilia-celery-sqs`
**URL:** `https://sqs.us-east-2.amazonaws.com/028780196116/ecofilia-celery-sqs`
**Tipo:** Standard Queue

| Parámetro | Valor |
|-----------|-------|
| Visibility Timeout | 3600 s (1 hora) |
| Message Retention | 345600 s (4 días) |
| Long Polling | Deshabilitado (wait=0) — configurado en Celery: 20s |

**Cómo funciona:**
1. El API encola tareas llamando a `.delay()` → mensaje llega a SQS
2. El Worker hace long polling de 20s a SQS consumiendo mensajes
3. Mientras el Worker procesa, el mensaje está "invisible" (visibility timeout 3600s)
4. Si el Worker termina OK → acknowledges → mensaje se elimina
5. Si el Worker falla/muere → mensaje vuelve a la cola después de 3600s → otro Worker lo retoma

---

## 8. Imágenes Docker — ECR

**Repositorio:** `ecofilia-api`
**URI:** `028780196116.dkr.ecr.us-east-2.amazonaws.com/ecofilia-api`

| Campo | Valor |
|-------|-------|
| Tag mutability | IMMUTABLE (no se puede sobreescribir un tag existente) |
| Scan on push | Habilitado (escaneo de vulnerabilidades automático) |
| Tags | SHA del commit de Git (ej: `54b5c2772d6...`) |

Cada deploy en GitHub Actions genera una imagen con el SHA del commit como tag. Esto garantiza trazabilidad total: sabés exactamente qué código corre en cada tarea ECS.

---

## 9. Secretos — Secrets Manager

**Secreto:** `ecofilia/prod`
**ARN:** `arn:aws:secretsmanager:us-east-2:028780196116:secret:ecofilia/prod-IqU5RD`

| Clave | Descripción |
|-------|-------------|
| `SECRET_KEY` | Django secret key |
| `JWT_SIGNING_KEY` | Clave de firma para JWT |
| `OPENAI_API_KEY` | API key de OpenAI |
| `POSTGRES_HOST` | Endpoint de RDS |
| `POSTGRES_PORT` | `5432` |
| `POSTGRES_NAME` | `postgres` |
| `POSTGRES_USER` | `postgres` |
| `POSTGRES_PASSWORD` | Contraseña de RDS |

Los valores se inyectan en los containers ECS como variables de entorno en tiempo de arranque. Nunca están en texto plano en el código ni en las task definitions.

---

## 10. Observabilidad — CloudWatch

### Log Groups

| Grupo | Retención | Qué loguea |
|-------|-----------|------------|
| `/ecs/ecofilia-api` | 30 días | Gunicorn access + error logs, Django logs |
| `/ecs/ecofilia-worker` | 30 días | Celery task logs, errores de procesamiento |
| `/ecs/ecofilia-beat` | 30 días | Celery beat scheduler logs |

### Cómo consultar logs

```bash
# Ver logs en tiempo real del API
aws logs tail /ecs/ecofilia-api --follow --region us-east-2

# Ver últimas 2 horas del worker
aws logs tail /ecs/ecofilia-worker --since 2h --region us-east-2

# Buscar errores
aws logs filter-log-events --log-group-name /ecs/ecofilia-api \
  --filter-pattern "ERROR" --region us-east-2
```

---

## 11. CI/CD — GitHub Actions

**Archivo:** `.github/workflows/deploy.yml`
**Repositorio:** `teodelcastillo/RAGv2-Fligoo`

### Trigger
Push a `main` que modifique archivos en `backend/**` o el propio workflow.

### Flujo

```
Push a main
    │
    ▼
Checkout del código
    │
    ▼
Autenticación AWS (OIDC — sin credenciales estáticas)
Rol: arn:aws:iam::028780196116:role/ecofilia-github-deploy
    │
    ▼
Login a ECR
    │
    ▼
docker build -f backend/docker/Dockerfile.prod
docker push → ECR con tag = ${{ github.sha }}
    │
    ▼
Actualizar task definition ecofilia-api  → Deploy API service
    │
    ▼
Actualizar task definition ecofilia-worker → Deploy Worker service
    │
    ▼
Actualizar task definition ecofilia-beat  → Deploy Beat service
    │
    ▼
wait-for-service-stability (rolling deploy sin downtime)
```

### Seguridad CI/CD
- Autenticación por OIDC (no hay AWS_ACCESS_KEY ni AWS_SECRET_KEY en GitHub Secrets)
- El rol `ecofilia-github-deploy` tiene permisos mínimos: solo ECR push + ECS update + IAM PassRole para los roles de tarea específicos
- Tags de imagen inmutables: no se puede sobrescribir una imagen ya deployada

---

## 12. DNS

El dominio `ecofilia.site` está registrado y gestionado en **Vercel** (nameservers `ns1.vercel-dns.com` / `ns2.vercel-dns.com`).

| Registro | Tipo | Apunta a |
|----------|------|----------|
| `ecofilia.site` | — | Frontend en Vercel |
| `www.ecofilia.site` | — | Frontend en Vercel |
| `api.ecofilia.site` | CNAME | `ecofilia-alb-2056124034.us-east-2.elb.amazonaws.com` |

El tráfico a `api.ecofilia.site` va: DNS → ALB → ECS API tasks.

> La Route53 Hosted Zone fue creada durante la migración pero está eliminada. Vercel gestiona el DNS.

---

## 13. Auto Scaling

### API (`ecofilia-api`)
| Métrica | Umbral | Acción |
|---------|--------|--------|
| CPU promedio | > 60% | Scale out |
| Memory promedio | > 70% | Scale out |
| Mínimo | — | 2 tareas |
| Máximo | — | 6 tareas |

### Worker (`ecofilia-worker`)
| Mínimo | Máximo |
|--------|--------|
| 1 tarea | 3 tareas |

El Beat no tiene auto scaling (siempre 1 instancia).

---

## 14. Costos estimados

Basado en us-east-2, precios de marzo 2026.

| Recurso | Detalle | $/mes |
|---------|---------|-------|
| ECS API | 2 tasks On-Demand, 512 CPU / 1024 MB | ~$36 |
| ECS Worker | 1 task Fargate Spot, 1024 CPU / 2048 MB | ~$11 |
| ECS Beat | 1 task Fargate Spot, 256 CPU / 512 MB | ~$3 |
| NAT Gateway | 1 × $0.045/h | ~$32 |
| RDS | db.t4g.micro + 20GB gp3 | ~$14 |
| ALB | ecofilia-alb | ~$6 |
| Secrets Manager | 1 secreto | ~$0.40 |
| ECR | ~500MB imagen | ~$0.05 |
| CloudWatch | Logs 30 días | ~$2 |
| SQS | Dentro de free tier | ~$0 |
| **Total fijo** | | **~$105/mes** |

**Costos variables:**
- NAT Gateway data: $0.045/GB (llamadas a OpenAI, pull de ECR, etc.)
- S3 `files-s3`: $0.023/GB almacenado + $0.0004/1k requests
- CloudWatch extra: $0.50/GB si supera 5GB/mes

---

## Referencia rápida de ARNs y IDs

```
Cluster ECS:       cluster-ecofilia
VPC:               vpc-016d5a3f84efb5f97
ALB ARN:           arn:aws:elasticloadbalancing:us-east-2:028780196116:loadbalancer/app/ecofilia-alb/182d5582dd6c2d41
RDS Endpoint:      ecofilia-db.cjsem8ewibzq.us-east-2.rds.amazonaws.com
ECR URI:           028780196116.dkr.ecr.us-east-2.amazonaws.com/ecofilia-api
SQS URL:           https://sqs.us-east-2.amazonaws.com/028780196116/ecofilia-celery-sqs
Secret ARN:        arn:aws:secretsmanager:us-east-2:028780196116:secret:ecofilia/prod-IqU5RD
NAT Gateway:       nat-08e76c4220fa768d7
SG ALB:            sg-049b3db6f9b45feb1
SG ECS API:        sg-0e751d4a7ed56c286
SG ECS Worker:     sg-060d35df0ec63c774
SG ECS Beat:       sg-0787290e7c847a49d
SG RDS:            sg-0748a16a26bf7c2c3
IAM Deploy Role:   arn:aws:iam::028780196116:role/ecofilia-github-deploy
IAM Task Role:     arn:aws:iam::028780196116:role/ecofiliaTaskRole
IAM Exec Role:     arn:aws:iam::028780196116:role/ecsTaskExecutionRole
```
