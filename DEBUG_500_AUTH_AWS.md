# Guía: Depurar error 500 en auth (token/refresh y me/) en AWS

El backend Django en api.ecofilia.site devuelve **500** cuando el frontend llama a:
- `POST /api/auth/token/refresh/` (refrescar sesión)
- `GET /api/auth/me/` (perfil del usuario)

Esta guía te ayuda a localizar la causa paso a paso.

---

## Paso 1: Conectar a la EC2 y ver logs en tiempo real

```bash
# Conectar por SSH (ajusta la ruta de la clave y la IP)
ssh -i /ruta/a/tu-clave.pem ubuntu@TU_IP_EC2

# Ver logs del contenedor Django
docker logs -f backend

# En otra terminal, ver logs de nginx
docker logs -f nginx
```

**Qué buscar:** Al hacer login y refrescar, deberían aparecer errores con traceback (si DEBUG=True) o al menos líneas de error.

---

## Paso 2: Revisar variables de entorno en producción

```bash
# Entrar al contenedor
docker exec -it backend bash

# Ver variables críticas (sin mostrar valores sensibles)
env | grep -E "POSTGRES|JWT|SECRET|SQS|ALLOWED|CORS|DEBUG"

# Salir
exit
```

**Verificar:**
- `POSTGRES_HOST`, `POSTGRES_NAME`, `POSTGRES_USER`, `POSTGRES_PASSWORD` → conexión a la base de datos
- `JWT_SIGNING_KEY` → debe coincidir con el usado en login (si cambió, los tokens viejos fallan)
- `SQS_QUEUE_URL` → obligatoria en prod; si falta, el app no arranca
- `ALLOWED_HOSTS` → debe incluir `api.ecofilia.site`
- `CORS_ALLOWED_ORIGINS` → debe incluir `https://www.ecofilia.site`
- `DEBUG` → en prod debe ser `False` (si es True, verás tracebacks en la respuesta)

---

## Paso 3: Probar la base de datos

```bash
docker exec -it backend python manage.py dbshell
```

Si entra al `psql`, la conexión funciona. Luego:

```sql
-- Verificar tablas de JWT blacklist (críticas para refresh)
\dt token_blacklist*

-- Deberían existir: token_blacklist_blacklistedtoken, token_blacklist_outstandingtoken
-- Si no existen, las migraciones no se aplicaron

\q
```

**Si las tablas no existen:**

```bash
docker exec -it backend python manage.py migrate token_blacklist
# O todas:
docker exec -it backend python manage.py migrate
```

---

## Paso 4: Probar token/refresh desde la EC2

```bash
# Obtener un refresh token haciendo login (desde tu máquina o Postman)
# Luego, desde la EC2:

curl -X POST http://localhost/api/auth/token/refresh/ \
  -H "Content-Type: application/json" \
  -d '{"refresh":"PEGA_AQUI_TU_REFRESH_TOKEN"}' \
  -v
```

**Interpretación:**
- `200` + JSON `{access, refresh}` → el backend funciona; el problema puede ser CORS, proxy o red
- `401` → token inválido/expirado/blacklisted
- `500` → error interno; revisar logs del contenedor en ese momento

---

## Paso 5: Revisar logs de Gunicorn/Django

```bash
# Logs recientes del backend
docker logs backend --tail 200

# Buscar líneas con "Error", "Exception", "Traceback"
docker logs backend 2>&1 | grep -A 5 -i "error\|exception\|traceback"
```

**Errores frecuentes:**
- `OperationalError` / `connection refused` → PostgreSQL inaccesible
- `ProgrammingError` / `relation "token_blacklist_..." does not exist` → migraciones faltantes
- `SQS_QUEUE_URL` / `RuntimeError` → variable de entorno faltante
- `JWT` / `InvalidToken` → clave o formato incorrecto

---

## Paso 6: Revisar nginx y red

```bash
# Logs de acceso y error de nginx
docker exec nginx cat /var/log/nginx/access.log | tail -50
docker exec nginx cat /var/log/nginx/error.log | tail -50

# Probar que nginx llega al backend
docker exec nginx curl -s -o /dev/null -w "%{http_code}" http://backend:8000/api/auth/token/refresh/ -X POST -H "Content-Type: application/json" -d '{}'
# Esperado: 400 (bad request) si no hay body válido, no 502/503
```

---

## Paso 7: Revisar Security Groups y red en AWS

1. **EC2 Security Group:** el puerto 80 (o 443) debe estar abierto para el tráfico entrante (0.0.0.0/0 o tu Load Balancer).
2. **RDS Security Group (si usas RDS):** debe permitir conexiones desde el Security Group de la EC2 en el puerto 5432.
3. **SQS:** la EC2 debe tener IAM Role o credenciales con permisos para la cola.

---

## Paso 8: Habilitar DEBUG temporalmente (solo para diagnosticar)

⚠️ **No dejar DEBUG=True en producción más de unos minutos.**

```bash
# Editar .env en la EC2
nano docker/.env
# Cambiar: DEBUG=True

# Reiniciar backend
docker-compose -f docker-compose-prod.yml restart backend

# Reproducir el error (login + refresh) y revisar la respuesta HTML
# Django mostrará el traceback completo

# Volver a DEBUG=False y reiniciar
```

---

## Resumen de checklist

| Revisión | Comando / Acción |
|----------|------------------|
| Logs backend | `docker logs backend --tail 200` |
| Variables env | `docker exec backend env \| grep POSTGRES` |
| Conexión DB | `docker exec backend python manage.py dbshell` |
| Tablas blacklist | `\dt token_blacklist*` en dbshell |
| Migraciones | `docker exec backend python manage.py showmigrations token_blacklist` |
| Probar refresh | `curl -X POST http://localhost/api/auth/token/refresh/ ...` |
| Logs nginx | `docker exec nginx tail -50 /var/log/nginx/error.log` |
| Security Groups | Consola AWS → EC2 → Security Groups |

---

## Hallazgos en el código (RAGv2-Fligoo)

1. **prod.py** exige `SQS_QUEUE_URL`; si falta, el app no arranca.
2. **Token blacklist** usa PostgreSQL (`OutstandingToken`, `BlacklistedToken`); las migraciones de `rest_framework_simplejwt.token_blacklist` deben estar aplicadas.
3. **CORS** incluye por defecto `www.ecofilia.site` y `ecofilia.vercel.app`.
4. **ALLOWED_HOSTS** por defecto incluye `api.ecofilia.site`.
5. No hay Redis; el throttle de DRF usa cache local (no debería provocar 500).
6. **CustomTokenRefreshView** usa `StrictRefreshThrottle` (20/min); un rate limit excedido devuelve 429, no 500.

Si tras estos pasos el 500 persiste, el traceback en los logs (o con DEBUG=True) indicará la causa exacta.
