# Referencia Rápida de Despliegue AWS

## 🚀 Comandos Rápidos para Despliegue

### Primera Vez (Despliegue Inicial)

```bash
# 1. Conectar a EC2
ssh -i /ruta/clave.pem ubuntu@TU_IP_EC2

# 2. Clonar repositorio
cd /opt
sudo mkdir -p ecofilia
sudo chown $USER:$USER ecofilia
cd ecofilia
git clone <URL_REPO> backend
cd backend/backend

# 3. Configurar .env
cp docker/template.env docker/.env
nano docker/.env  # Editar con valores de producción

# 4. Desplegar (usando script automatizado)
chmod +x deploy-aws.sh
./deploy-aws.sh

# O manualmente:
docker-compose -f docker-compose-prod.yml build
docker-compose -f docker-compose-prod.yml up -d
docker-compose -f docker-compose-prod.yml exec backend python manage.py migrate
docker-compose -f docker-compose-prod.yml exec backend python manage.py collectstatic --noinput
```

### Actualización (Con Cambios)

```bash
# 1. Conectar a EC2
ssh -i /ruta/clave.pem ubuntu@TU_IP_EC2

# 2. Ir al proyecto
cd /opt/ecofilia/backend/backend

# 3. Actualizar código
git pull origin main

# 4. Desplegar
./deploy-aws.sh

# O si solo cambió código (sin dependencias):
./deploy-aws.sh --skip-build

# O si no hay migraciones:
./deploy-aws.sh --skip-migrations
```

## 📋 Comandos Útiles

### Ver Logs
```bash
# Todos los servicios
docker-compose -f docker-compose-prod.yml logs -f

# Servicio específico
docker-compose -f docker-compose-prod.yml logs -f backend
docker-compose -f docker-compose-prod.yml logs -f celery-worker
docker-compose -f docker-compose-prod.yml logs -f nginx
```

### Estado de Contenedores
```bash
docker-compose -f docker-compose-prod.yml ps
docker stats
```

### Reiniciar Servicios
```bash
# Reiniciar todo
docker-compose -f docker-compose-prod.yml restart

# Reiniciar un servicio específico
docker-compose -f docker-compose-prod.yml restart backend
```

### Detener/Eliminar
```bash
# Detener
docker-compose -f docker-compose-prod.yml stop

# Detener y eliminar contenedores
docker-compose -f docker-compose-prod.yml down

# Detener, eliminar contenedores y volúmenes
docker-compose -f docker-compose-prod.yml down -v
```

### Base de Datos
```bash
# Migraciones
docker-compose -f docker-compose-prod.yml exec backend python manage.py migrate

# Shell de Django
docker-compose -f docker-compose-prod.yml exec backend python manage.py shell

# Crear superusuario
docker-compose -f docker-compose-prod.yml exec backend python manage.py createsuperuser

# Shell de base de datos
docker-compose -f docker-compose-prod.yml exec backend python manage.py dbshell
```

### Celery
```bash
# Ver workers activos
docker-compose -f docker-compose-prod.yml exec celery-worker celery -A main inspect active

# Ver tareas registradas
docker-compose -f docker-compose-prod.yml exec celery-worker celery -A main inspect registered

# Ping al worker
docker-compose -f docker-compose-prod.yml exec celery-worker celery -A main inspect ping
```

### Archivos Estáticos
```bash
# Recolectar estáticos
docker-compose -f docker-compose-prod.yml exec backend python manage.py collectstatic --noinput

# Verificar que se crearon
ls -la main/django-static/
```

## 🔍 Verificación Post-Despliegue

```bash
# Health check
curl http://localhost/api/

# Verificar que nginx sirve estáticos
curl http://localhost/django-static/

# Verificar admin (debe requerir auth)
curl -I http://localhost/admin/
```

## 🐛 Troubleshooting Rápido

### Contenedor no inicia
```bash
docker-compose -f docker-compose-prod.yml logs [nombre-servicio]
docker-compose -f docker-compose-prod.yml ps
```

### Error de conexión a DB
```bash
# Verificar variables de entorno
docker-compose -f docker-compose-prod.yml exec backend env | grep POSTGRES

# Probar conexión
docker-compose -f docker-compose-prod.yml exec backend python manage.py dbshell
```

### Celery no funciona
```bash
# Ver logs
docker-compose -f docker-compose-prod.yml logs celery-worker

# Verificar SQS
docker-compose -f docker-compose-prod.yml exec celery-worker env | grep SQS
```

### Puerto 80 ocupado
```bash
sudo lsof -i :80
sudo systemctl stop apache2  # o nginx
```

## 📝 Variables de Entorno Críticas

Asegúrate de tener estas en `docker/.env`:

```bash
DJANGO_SETTINGS_MODULE=main.settings.prod
SECRET_KEY=...
DEBUG=False
POSTGRES_HOST=...
POSTGRES_PASSWORD=...
AWS_STORAGE_BUCKET_NAME=...
SQS_QUEUE_URL=...
OPENAI_API_KEY=...
```

## 🔗 Enlaces Útiles

- Guía completa: `AWS_DEPLOYMENT_GUIDE.md`
- Documentación técnica: `backend/TECHNICAL_DOCUMENTATION.md`
- API docs: `backend/API_DOCUMENTATION.md`

