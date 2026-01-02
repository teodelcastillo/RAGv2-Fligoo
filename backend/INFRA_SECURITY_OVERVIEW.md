# Ecofilia - Hoja de Infraestructura y Seguridad

Alcance: Backend Django/DRF + Celery, despliegue en AWS (EC2 + ALB + RDS + S3 + SQS), autenticación JWT con MFA opcional.

## 1. Visión General
- Backend: Django 5 + DRF, PostgreSQL 16 (+pgvector), Celery para tareas async.
- Autenticación: JWT (rotación + blacklist), MFA TOTP opcional, verificación de email obligatoria.
- Procesos clave: ingestión de documentos, chunking/embeddings OpenAI, búsqueda semántica/RAG, chat y evaluaciones.
- Despliegue actual: EC2 única (t3.small) detrás de ALB, storage S3, cola SQS, base de datos RDS PostgreSQL.

## 2. Arquitectura Lógica
- API stateless con JWT; endpoints sensibles con throttling (refresh dedicado).
- Tareas async: Celery consume de SQS para procesamiento de documentos/evaluaciones.
- Storage: archivos en S3 (`files-ecofilia-s3`), filesystem local sólo en desarrollo.
- Datos: PostgreSQL en RDS, extensión pgvector habilitada para búsqueda vectorial.
- Observabilidad base: logs de aplicación (Docker/servidor); sin stack APM ni dashboards dedicados aún.

## 3. Seguridad de Aplicación
- Autenticación: JWT con `ROTATE_REFRESH_TOKENS=True` y `BLACKLIST_AFTER_ROTATION=True`; MFA TOTP opcional; bloqueo si email no verificado.
- Autorización: permisos DRF + filtros de dominio (propietario, público, shares, proyectos) en RAG/chat/evaluaciones.
- Protección de credenciales: refresh tokens invalidados en logout y eventos sensibles; throttling `strict_refresh` (20/min por defecto).
- Cabeceras/HTTPS: `SESSION_COOKIE_HTTPONLY`, `CSRF_COOKIE_HTTPONLY`, `SameSite=Lax` por defecto; `SECURE_SSL_REDIRECT` configurable; HSTS configurable.
- Manejo de datos sensibles: tokens no se loguean; respuestas de error genéricas.

## 4. Infraestructura AWS
- Cuenta: 028780196116 (sin AWS Organizations). MFA forzado para consola/IAM.
- Región: us-east-2 (primaria).
- Red:
  - ALB en subnets públicas.
  - EC2 backend en subnets privadas.
  - NAT Gateway y VPC Endpoints (S3/SQS/STS/Secrets) para tráfico privado.
 - Capa Web:
   - Application Load Balancer (ALB).
  - Certificados TLS:
    - Backend/API (`api.ecofilia.site`): certificado emitido por Amazon (ACM), RSA 2048, vigente y cumpliendo requisitos.
    - Frontend: dominio y certificados gestionados por Vercel.
  - WAF: habilitado en ALB; además Vercel WAF (Firewall) activo con logging, bloqueo/desafío, reglas personalizadas, IP blocking y managed rulesets; cambios se propagan globalmente en ~300 ms con rollback inmediato.
- Compute:
  - EC2 (single instance) t3.small. Sin Auto Scaling Group hoy.
- Base de Datos:
  - RDS PostgreSQL.
  - Encriptado at rest con KMS gestionado por AWS.
- Storage:
  - S3 bucket `files-ecofilia-s3` (us-east-2), ARN `arn:aws:s3:::files-ecofilia-s3`.
  - Default encryption SSE-S3. Versioning deshabilitado. Access logs deshabilitados.
- Colas:
  - SQS standard, cola `celery` (URL en vars de entorno). 
- Identidad y Acceso:
  - EC2 con Instance Profile (IAM Role), sin access keys estáticas.
  - Principio de mínimo privilegio:
    - S3: Get/Put/List restringido a bucket/prefix.
    - SQS: Send/Receive/Delete/GetAttributes restringido a la cola.
    - KMS: Encrypt/Decrypt/GenerateDataKey limitado a la clave usada.
- Observabilidad:
  - Logs: solo los propios de app. Sin CloudWatch dashboards/alarms ni APM hoy.
- CI/CD:
  - Despliegue manual en EC2 (SSH + git pull + docker compose up -d). Sin pipeline ni ECR.
- Resiliencia/DR:
  - Sin región de respaldo. (Pendiente) RPO/RTO, snapshots cross-region y pruebas de restauración.

