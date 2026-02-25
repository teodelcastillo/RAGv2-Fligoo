# Actualizar Contenedores con Últimos Cambios

Ya que hiciste `git pull` y trajiste los últimos cambios, ahora necesitas actualizar los contenedores.

## 🚀 Opción 1: Script Automatizado (Recomendado)

Si tienes el script `deploy-aws.sh` en tu EC2:

```bash
# Desde el directorio backend/backend en EC2
cd /ruta/a/tu/proyecto/backend/backend

# Ejecutar el script (reconstruye imagen, reinicia contenedores, migraciones, etc.)
./deploy-aws.sh
```

El script automáticamente:
- ✅ Reconstruye la imagen Docker con los nuevos cambios
- ✅ Detiene los contenedores actuales
- ✅ Levanta los nuevos contenedores
- ✅ Ejecuta migraciones (si hay)
- ✅ Recolecta archivos estáticos
- ✅ Verifica que todo esté funcionando

---

## 🔧 Opción 2: Comandos Manuales

Si prefieres hacerlo paso a paso:

### Paso 1: Reconstruir la Imagen Docker

```bash
# Reconstruir la imagen con los nuevos cambios
docker-compose -f docker-compose-prod.yml build
```

### Paso 2: Reiniciar los Contenedores

```bash
# Detener los contenedores actuales
docker-compose -f docker-compose-prod.yml down

# Levantar los nuevos contenedores con la imagen actualizada
docker-compose -f docker-compose-prod.yml up -d
```

**O en un solo comando:**
```bash
# Esto reconstruye y reinicia todo
docker-compose -f docker-compose-prod.yml up -d --build
```

### Paso 3: Ejecutar Migraciones (si hay cambios en la BD)

```bash
# Verificar si hay migraciones pendientes
docker-compose -f docker-compose-prod.yml exec backend python manage.py showmigrations

# Aplicar migraciones
docker-compose -f docker-compose-prod.yml exec backend python manage.py migrate
```

### Paso 4: Recolectar Archivos Estáticos (si hay cambios)

```bash
docker-compose -f docker-compose-prod.yml exec backend python manage.py collectstatic --noinput
```

### Paso 5: Verificar que Todo Funciona

```bash
# Ver estado de contenedores
docker-compose -f docker-compose-prod.yml ps

# Ver logs
docker-compose -f docker-compose-prod.yml logs -f

# Probar la API
curl http://localhost/api/
```

---

## ⚡ Opción 3: Actualización Rápida (Solo Código, Sin Dependencias)

Si **solo cambió código Python** (no dependencias en `pyproject.toml` o `Dockerfile`):

```bash
# Reiniciar contenedores (recargarán el código desde el volumen montado)
docker-compose -f docker-compose-prod.yml restart backend celery-worker

# Si usas Gunicorn, puede que necesites hacer rebuild para que cargue el nuevo código
docker-compose -f docker-compose-prod.yml up -d --build --no-deps backend celery-worker
```

**Nota:** Si tu `docker-compose-prod.yml` monta el código como volumen (`- .:/code`), a veces solo reiniciar es suficiente. Pero es más seguro hacer rebuild.

---

## 📋 Comandos Útiles Durante la Actualización

### Ver qué está pasando en tiempo real:

```bash
# Ver logs de todos los servicios
docker-compose -f docker-compose-prod.yml logs -f

# Ver logs de un servicio específico
docker-compose -f docker-compose-prod.yml logs -f backend
```

### Si algo sale mal, puedes volver atrás:

```bash
# Ver imágenes disponibles
docker images | grep backend

# Si necesitas usar una imagen anterior (si la guardaste con tag)
docker tag backend:previous backend:latest
docker-compose -f docker-compose-prod.yml up -d
```

---

## ✅ Checklist Post-Actualización

Después de actualizar, verifica:

- [ ] Contenedores están corriendo: `docker-compose -f docker-compose-prod.yml ps`
- [ ] API responde: `curl http://localhost/api/`
- [ ] Celery worker funciona: `docker-compose -f docker-compose-prod.yml exec celery-worker celery -A main inspect ping`
- [ ] No hay errores en logs: `docker-compose -f docker-compose-prod.yml logs --tail=50`

---

## 🐛 Si Algo Sale Mal

### Los contenedores no inician:

```bash
# Ver logs detallados
docker-compose -f docker-compose-prod.yml logs

# Verificar el archivo .env
cat docker/.env

# Reconstruir desde cero
docker-compose -f docker-compose-prod.yml down
docker-compose -f docker-compose-prod.yml build --no-cache
docker-compose -f docker-compose-prod.yml up -d
```

### La aplicación no responde:

```bash
# Verificar que los contenedores están corriendo
docker-compose -f docker-compose-prod.yml ps

# Ver logs del backend
docker-compose -f docker-compose-prod.yml logs backend

# Verificar nginx
docker-compose -f docker-compose-prod.yml logs nginx
```

---

## 💡 Recomendación

**Usa el script automatizado** (`./deploy-aws.sh`) porque:
- ✅ Hace todo el proceso de forma segura
- ✅ Verifica cada paso
- ✅ Te muestra qué está pasando
- ✅ Maneja errores automáticamente

Solo necesitas ejecutar:
```bash
cd /ruta/a/tu/proyecto/backend/backend
./deploy-aws.sh
```

¡Y listo! 🎉




