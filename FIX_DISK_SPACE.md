# Solución: Disco Lleno en EC2

## 🔴 Problema

El error `no space left on device` indica que el disco de tu instancia EC2 está lleno. Esto ocurre porque Docker intenta copiar archivos grandes (como logs de nginx) durante el build.

## ✅ Solución Paso a Paso

### Paso 1: Verificar Espacio en Disco

Ejecuta en tu EC2:

```bash
# Ver uso de disco
df -h

# Ver qué está ocupando más espacio
du -sh /* 2>/dev/null | sort -hr | head -10
```

### Paso 2: Limpiar Espacio

#### 2.1 Limpiar Docker (IMPORTANTE)

```bash
# Ver cuánto espacio usa Docker
docker system df

# Limpiar TODO lo que no se esté usando
docker system prune -a --volumes

# Esto eliminará:
# - Imágenes no usadas
# - Contenedores detenidos
# - Volúmenes no usados
# - Redes no usadas
# - Build cache
```

**⚠️ ADVERTENCIA:** Esto eliminará imágenes y contenedores que no estén en uso. Si tienes contenedores corriendo, no se eliminarán.

#### 2.2 Limpiar Logs de Nginx

```bash
# Ir al directorio del proyecto
cd ~/ecofilia/backend

# Ver tamaño de los logs
du -sh logs/

# Vaciar los logs (NO eliminar el directorio, solo el contenido)
truncate -s 0 logs/nginx/*.log 2>/dev/null || true

# O eliminar logs antiguos
find logs/ -name "*.log" -type f -mtime +7 -delete
```

#### 2.3 Limpiar Logs del Sistema

```bash
# Limpiar logs del sistema (opcional)
sudo journalctl --vacuum-time=7d

# Limpiar paquetes no usados
sudo apt-get autoremove -y
sudo apt-get autoclean -y
```

### Paso 3: Crear/Actualizar .dockerignore

Ya creé un archivo `.dockerignore` en `backend/.dockerignore` que excluye:
- Logs
- Archivos de Python compilados
- Archivos temporales
- Media y static files (se generan en runtime)

**Asegúrate de que existe en tu EC2:**

```bash
cd ~/ecofilia/backend
ls -la .dockerignore
```

Si no existe, créalo con el contenido que proporcioné.

### Paso 4: Reintentar el Build

```bash
# Asegúrate de estar en el directorio correcto
cd ~/ecofilia/backend

# Verificar espacio disponible ahora
df -h

# Reintentar el build
docker-compose -f docker-compose-prod.yml up -d --build
```

## 🔍 Verificar Qué Está Ocupando Espacio

### Ver Tamaño de Directorios

```bash
# Ver los directorios más grandes
du -h --max-depth=1 ~/ecofilia | sort -hr

# Ver tamaño de logs específicamente
du -sh ~/ecofilia/backend/logs/
```

### Ver Imágenes Docker

```bash
# Ver todas las imágenes y su tamaño
docker images

# Ver contenedores y su tamaño
docker ps -a --size
```

## 🛠️ Comandos de Limpieza Completa

Si necesitas más espacio, ejecuta estos comandos en orden:

```bash
# 1. Detener contenedores (si es necesario)
docker-compose -f docker-compose-prod.yml down

# 2. Limpiar Docker completamente
docker system prune -a --volumes -f

# 3. Limpiar logs
cd ~/ecofilia/backend
find logs/ -name "*.log" -type f -delete 2>/dev/null || true

# 4. Limpiar archivos temporales
find ~/ecofilia/backend -name "*.pyc" -delete
find ~/ecofilia/backend -name "__pycache__" -type d -exec rm -r {} + 2>/dev/null || true

# 5. Verificar espacio
df -h
```

## 📊 Monitoreo Continuo

Para evitar que vuelva a pasar:

### Configurar Rotación de Logs

Crea un script para rotar logs automáticamente:

```bash
# Crear script de limpieza
cat > ~/cleanup-logs.sh << 'EOF'
#!/bin/bash
# Limpiar logs mayores a 100MB
find ~/ecofilia/backend/logs -name "*.log" -size +100M -delete
# Vaciar logs actuales si son muy grandes
find ~/ecofilia/backend/logs -name "*.log" -exec truncate -s 50M {} \;
EOF

chmod +x ~/cleanup-logs.sh

# Agregar a crontab para ejecutar semanalmente
(crontab -l 2>/dev/null; echo "0 2 * * 0 $HOME/cleanup-logs.sh") | crontab -
```

### Monitorear Espacio

```bash
# Ver espacio disponible
df -h | grep -E '^/dev/'

# Alertar si el disco está > 80% lleno
df -h | awk '$5+0 > 80 {print "ALERTA: Disco " $1 " está " $5 " lleno"}'
```

## ✅ Verificación Post-Limpieza

Después de limpiar, verifica:

```bash
# Espacio disponible
df -h

# Docker limpio
docker system df

# Logs bajo control
du -sh ~/ecofilia/backend/logs/
```

## 🚨 Si Aún No Hay Espacio

Si después de limpiar aún no hay suficiente espacio:

1. **Aumentar el tamaño del volumen EBS** en AWS Console
2. **Eliminar archivos grandes manualmente**
3. **Mover logs a S3** y eliminarlos localmente
4. **Usar un volumen EBS adicional** para logs

## 💡 Prevención Futura

1. ✅ Usar `.dockerignore` (ya creado)
2. ✅ Configurar rotación de logs
3. ✅ Limpiar Docker regularmente
4. ✅ Monitorear espacio en disco
5. ✅ Considerar aumentar el tamaño del volumen EBS

---

**Después de limpiar, ejecuta:**

```bash
cd ~/ecofilia/backend
docker-compose -f docker-compose-prod.yml up -d --build
```

¡Debería funcionar ahora! 🎉

