# Guía de Despliegue en AWS - Ecofilia Backend

Esta guía te llevará paso a paso para desplegar el backend de Ecofilia en AWS con tus últimos cambios.

## 📋 Prerrequisitos

Antes de comenzar, asegúrate de tener:

- ✅ Acceso a una instancia EC2 en AWS
- ✅ Credenciales de AWS configuradas (AWS CLI o IAM)
- ✅ PostgreSQL con pgvector (RDS o instancia externa)
- ✅ Bucket S3 creado y configurado
- ✅ Cola SQS creada para Celery
- ✅ Clave SSH para acceder a la instancia EC2
- ✅ Git configurado con acceso al repositorio

---

## 🔧 Paso 1: Preparar el Entorno Local

### 1.1 Verificar Cambios Locales

```bash
# Asegúrate de estar en el directorio del proyecto
cd backend

# Verifica el estado de Git
git status

# Revisa los últimos commits
git log --oneline -10

# Si tienes cambios sin commitear, haz commit
git add .
git commit -m "Preparación para despliegue en AWS"
```

### 1.2 Verificar Archivos de Configuración

Asegúrate de que estos archivos estén actualizados:
- `docker-compose-prod.yml`
- `docker/Dockerfile`
- `docker/entrypoint-prod.sh`
- `nginx/default.conf`
- `main/settings/prod.py`

---

## 🚀 Paso 2: Conectar a la Instancia EC2

### 2.1 Conectar vía SSH

```bash
# Reemplaza con tu IP y clave
ssh -i /ruta/a/tu/clave.pem ubuntu@TU_IP_EC2

# O si usas ec2-user (Amazon Linux)
ssh -i /ruta/a/tu/clave.pem ec2-user@TU_IP_EC2
```

### 2.2 Verificar Instalaciones en EC2

```bash
# Verificar Docker
docker --version
docker-compose --version

# Si no están instalados, instálalos:
# Para Ubuntu/Debian:
sudo apt-get update
sudo apt-get install -y docker.io docker-compose

# Para Amazon Linux:
sudo yum install -y docker
sudo service docker start
sudo usermod -a -G docker ec2-user
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verificar Git
git --version
```

---

## 📦 Paso 3: Clonar/Actualizar el Repositorio en EC2

### 3.1 Si es la Primera Vez (Clonar)

```bash
# Navegar al directorio donde quieres el proyecto
cd ~
# O crear un directorio específico
mkdir -p /opt/ecofilia
cd /opt/ecofilia

# Clonar el repositorio
git clone <URL_DEL_REPOSITORIO> backend
cd backend/backend
```

### 3.2 Si Ya Existe (Actualizar)

```bash
# Navegar al directorio del proyecto
cd /opt/ecofilia/backend/backend
# O donde tengas el proyecto

# Obtener los últimos cambios
git fetch origin
git pull origin main
# O la rama que uses: git pull origin develop
```

---

## ⚙️ Paso 4: Configurar Variables de Entorno

### 4.1 Crear/Actualizar el Archivo .env

```bash
# Copiar el template si no existe
cp docker/template.env docker/.env

# Editar el archivo .env con tus valores de producción
nano docker/.env
# O usar vi: vi docker/.env
```

### 4.2 Configurar Variables de Producción

Edita `docker/.env` con estos valores (ajusta según tu configuración):

```bash
# Django Settings
DJANGO_SETTINGS_MODULE=main.settings.prod
SECRET_KEY=TU_SECRET_KEY_MUY_SEGURO_AQUI
DEBUG=False

# Hosts
ALLOWED_HOSTS=tu-dominio.com,tu-ip-ec2,localhost
CORS_ALLOWED_ORIGINS=https://tu-frontend.com,https://www.tu-frontend.com
CSRF_TRUSTED_ORIGINS=https://tu-frontend.com,https://www.tu-frontend.com

# JWT
JWT_SIGNING_KEY=TU_JWT_SIGNING_KEY_SEGURO
JWT_ACCESS_TTL_MINUTES=15
JWT_REFRESH_TTL_DAYS=7
JWT_ALGORITHM=HS256

# Security (Producción)
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SAMESITE=Lax

# Throttling
DRF_THROTTLE_RATE_ANON=30/min
DRF_THROTTLE_RATE_USER=120/min

# Email
DEFAULT_FROM_EMAIL=noreply@ecofilia.com
FRONTEND_BASE_URL=https://tu-frontend.com
MFA_ISSUER_NAME=Ecofilia

# Database (RDS o PostgreSQL externo)
POSTGRES_USER=tu_usuario_db
POSTGRES_PASSWORD=tu_password_db_seguro
POSTGRES_NAME=ecofilia_db
POSTGRES_HOST=tu-rds-endpoint.region.rds.amazonaws.com
POSTGRES_PORT=5432

# OpenAI
OPENAI_API_KEY=sk-tu-api-key-de-produccion
MODEL_EMBEDDING=text-embedding-3-small
MODEL_COMPLETION=gpt-4o-mini
CHAT_CONTEXT_CHUNKS=4
EVALUATION_CONTEXT_CHUNKS=6
CHAT_HISTORY_MESSAGES=10

# AWS SQS (Celery)
SQS_QUEUE_URL=https://sqs.us-east-2.amazonaws.com/TU_ACCOUNT_ID/eco-celery-sqs
SQS_REGION=us-east-2

# AWS S3
AWS_STORAGE_BUCKET_NAME=tu-bucket-s3
AWS_S3_REGION_NAME=us-east-2

# AWS Credentials (si no usas IAM Role en EC2)
AWS_ACCESS_KEY_ID=tu-access-key
AWS_SECRET_ACCESS_KEY=tu-secret-key
```

**⚠️ IMPORTANTE:**
- Genera `SECRET_KEY` y `JWT_SIGNING_KEY` seguros (puedes usar: `python -c "import secrets; print(secrets.token_urlsafe(50))"`)
- No subas este archivo a Git (debe estar en `.gitignore`)
- Si tu EC2 tiene un IAM Role con permisos, no necesitas `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY`

---

## 🐳 Paso 5: Construir y Desplegar con Docker

### 5.1 Detener Contenedores Existentes (si hay)

```bash
# Si ya tienes contenedores corriendo
docker-compose -f docker-compose-prod.yml down

# O si quieres eliminar también los volúmenes
docker-compose -f docker-compose-prod.yml down -v
```

### 5.2 Construir la Imagen Docker

```bash
# Construir la imagen de producción
docker build -f docker/Dockerfile -t backend:latest .

# Verificar que la imagen se creó
docker images | grep backend
```

### 5.3 Iniciar los Servicios

```bash
# Levantar todos los servicios en modo detached
docker-compose -f docker-compose-prod.yml up -d

# Verificar que los contenedores están corriendo
docker-compose -f docker-compose-prod.yml ps
```

Deberías ver 3 contenedores corriendo:
- `backend`
- `celery-worker`
- `nginx`

---

## 🗄️ Paso 6: Ejecutar Migraciones de Base de Datos

### 6.1 Aplicar Migraciones

```bash
# Ejecutar migraciones
docker-compose -f docker-compose-prod.yml exec backend python manage.py migrate

# Si hay errores, verifica la conexión a la base de datos
docker-compose -f docker-compose-prod.yml exec backend python manage.py dbshell
```

### 6.2 Verificar Estado de la Base de Datos

```bash
# Verificar que las tablas se crearon correctamente
docker-compose -f docker-compose-prod.yml exec backend python manage.py showmigrations
```

---

## 📁 Paso 7: Recolectar Archivos Estáticos

```bash
# Recolectar archivos estáticos de Django
docker-compose -f docker-compose-prod.yml exec backend python manage.py collectstatic --noinput
```

Esto creará los archivos estáticos en `main/django-static/` que nginx servirá.

---

## 👤 Paso 8: Crear Superusuario (si es necesario)

```bash
# Crear un superusuario para acceder al admin
docker-compose -f docker-compose-prod.yml exec backend python manage.py createsuperuser
```

Sigue las instrucciones para crear el usuario.

---

## 🔍 Paso 9: Verificar el Despliegue

### 9.1 Verificar Logs

```bash
# Ver logs de todos los servicios
docker-compose -f docker-compose-prod.yml logs -f

# Ver logs de un servicio específico
docker-compose -f docker-compose-prod.yml logs -f backend
docker-compose -f docker-compose-prod.yml logs -f celery-worker
docker-compose -f docker-compose-prod.yml logs -f nginx
```

### 9.2 Verificar Estado de los Contenedores

```bash
# Ver estado de los contenedores
docker-compose -f docker-compose-prod.yml ps

# Verificar que los puertos están abiertos
sudo netstat -tlnp | grep :80
```

### 9.3 Probar la API

```bash
# Desde la instancia EC2
curl http://localhost/api/

# O desde tu máquina local (reemplaza con tu IP pública)
curl http://TU_IP_PUBLICA/api/
```

### 9.4 Verificar Celery Worker

```bash
# Verificar que el worker de Celery está funcionando
docker-compose -f docker-compose-prod.yml exec celery-worker celery -A main inspect active
```

---

## 🔒 Paso 10: Configurar Seguridad en AWS

### 10.1 Security Group de EC2

Asegúrate de que tu Security Group tenga estas reglas:

- **Entrada (Inbound):**
  - Puerto 80 (HTTP) desde 0.0.0.0/0 (o tu IP específica)
  - Puerto 443 (HTTPS) si usas SSL
  - Puerto 22 (SSH) solo desde tu IP

- **Salida (Outbound):**
  - Todo el tráfico (0.0.0.0/0)

### 10.2 IAM Role para EC2 (Recomendado)

En lugar de usar credenciales en el `.env`, configura un IAM Role para tu instancia EC2 con permisos para:
- S3 (lectura/escritura en tu bucket)
- SQS (enviar/recibir mensajes)

### 10.3 Configurar SSL/HTTPS (Opcional pero Recomendado)

Para producción, configura SSL usando:
- **AWS Certificate Manager (ACM)** + **Application Load Balancer (ALB)**
- O **Let's Encrypt** con Certbot en la instancia

---

## 🔄 Paso 11: Actualizaciones Futuras

Para futuros despliegues con cambios:

```bash
# 1. Conectar a EC2
ssh -i /ruta/a/clave.pem ubuntu@TU_IP_EC2

# 2. Ir al directorio del proyecto
cd /opt/ecofilia/backend/backend

# 3. Obtener últimos cambios
git pull origin main

# 4. Reconstruir imagen (si hay cambios en dependencias o código)
docker-compose -f docker-compose-prod.yml build

# 5. Reiniciar servicios
docker-compose -f docker-compose-prod.yml down
docker-compose -f docker-compose-prod.yml up -d

# 6. Ejecutar migraciones (si hay nuevas)
docker-compose -f docker-compose-prod.yml exec backend python manage.py migrate

# 7. Recolectar estáticos (si hay cambios)
docker-compose -f docker-compose-prod.yml exec backend python manage.py collectstatic --noinput

# 8. Verificar logs
docker-compose -f docker-compose-prod.yml logs -f
```

---

## 🐛 Solución de Problemas Comunes

### Problema: Contenedores no inician

```bash
# Ver logs detallados
docker-compose -f docker-compose-prod.yml logs

# Verificar el archivo .env
cat docker/.env

# Verificar permisos
ls -la docker/.env
```

### Problema: Error de conexión a base de datos

```bash
# Verificar variables de entorno
docker-compose -f docker-compose-prod.yml exec backend env | grep POSTGRES

# Probar conexión manual
docker-compose -f docker-compose-prod.yml exec backend python manage.py dbshell
```

### Problema: Celery no procesa tareas

```bash
# Verificar logs de Celery
docker-compose -f docker-compose-prod.yml logs celery-worker

# Verificar conexión a SQS
docker-compose -f docker-compose-prod.yml exec celery-worker celery -A main inspect ping
```

### Problema: Archivos estáticos no se cargan

```bash
# Verificar que se recolectaron
ls -la main/django-static/

# Verificar permisos de nginx
docker-compose -f docker-compose-prod.yml exec nginx ls -la /opt/app/django-static/
```

### Problema: Puerto 80 ya en uso

```bash
# Ver qué está usando el puerto 80
sudo lsof -i :80

# Detener el servicio que lo está usando
sudo systemctl stop apache2  # o nginx, según corresponda
```

---

## 📊 Monitoreo Post-Despliegue

### Verificar Salud de la Aplicación

```bash
# Health check básico
curl http://localhost/api/

# Verificar admin (debería requerir autenticación)
curl http://localhost/admin/
```

### Monitorear Recursos

```bash
# Uso de recursos de contenedores
docker stats

# Espacio en disco
df -h

# Memoria disponible
free -h
```

### Logs Persistentes

Los logs de nginx se guardan en `./logs/nginx/` según `docker-compose-prod.yml`.

---

## ✅ Checklist Final

Antes de considerar el despliegue completo, verifica:

- [ ] Todos los contenedores están corriendo (`docker-compose ps`)
- [ ] Las migraciones se aplicaron correctamente
- [ ] Los archivos estáticos se recolectaron
- [ ] La API responde correctamente
- [ ] Celery worker está procesando tareas
- [ ] La conexión a S3 funciona (subir un archivo de prueba)
- [ ] La conexión a SQS funciona (enviar una tarea de prueba)
- [ ] El Security Group permite tráfico en el puerto 80
- [ ] Las variables de entorno están correctamente configuradas
- [ ] Los logs no muestran errores críticos

---

## 📝 Notas Adicionales

1. **Backups**: Configura backups automáticos de tu base de datos RDS
2. **Monitoreo**: Considera usar CloudWatch para monitorear la instancia EC2
3. **Escalabilidad**: Para mayor tráfico, considera usar un Application Load Balancer con múltiples instancias
4. **SSL**: Configura HTTPS usando ACM o Let's Encrypt
5. **Dominio**: Configura un dominio personalizado apuntando a tu IP pública o ALB

---

## 🆘 Soporte

Si encuentras problemas durante el despliegue:

1. Revisa los logs: `docker-compose -f docker-compose-prod.yml logs`
2. Verifica la documentación técnica: `backend/TECHNICAL_DOCUMENTATION.md`
3. Revisa la configuración de AWS (Security Groups, IAM, etc.)

---

**¡Despliegue completado! 🎉**

Tu aplicación debería estar disponible en `http://TU_IP_PUBLICA/api/`

