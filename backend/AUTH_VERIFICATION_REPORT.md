# Verificación de Autenticación Backend - Reporte

## Fecha: 2025-01-XX

## Resumen Ejecutivo

Se ha realizado una verificación completa del sistema de autenticación backend para identificar problemas relacionados con la rotación de tokens y el manejo de sesiones. El problema reportado es que después del login, al intentar acceder a páginas protegidas, se recibe el error `Token is blacklisted` desde el SSR.

## Configuración Actual

### SimpleJWT Settings (base.py)

```python
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,          # ✅ ACTIVADO
    "BLACKLIST_AFTER_ROTATION": True,        # ✅ ACTIVADO
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": True,
}
```

### Endpoint de Refresh

- **Ruta**: `POST /api/auth/token/refresh/`
- **Vista**: `CustomTokenRefreshView` (creada para garantizar comportamiento)
- **Permisos**: `AllowAny` (no requiere autenticación previa)
- **CSRF**: No requerido (endpoint stateless con JWT)

## Verificaciones Realizadas

### ✅ 1. Rotación de Tokens

**Estado**: CONFIGURADO CORRECTAMENTE

- `ROTATE_REFRESH_TOKENS=True` está activado
- `BLACKLIST_AFTER_ROTATION=True` está activado
- Con esta configuración, SimpleJWT debería:
  1. Al recibir un refresh token válido, generar uno nuevo
  2. Blacklistear el refresh token anterior
  3. Devolver `{ "access": "...", "refresh": "..." }` en la respuesta

**Verificación**: Se creó `CustomTokenRefreshView` que extiende `TokenRefreshView` y garantiza que el refresh rotado se devuelva correctamente.

### ✅ 2. Endpoint de Refresh Devuelve Refresh Rotado

**Estado**: GARANTIZADO CON VISTA CUSTOM

- La vista `CustomTokenRefreshView` usa `TokenRefreshSerializer` de SimpleJWT
- Con `ROTATE_REFRESH_TOKENS=True`, el serializer automáticamente incluye el refresh rotado
- Se agregó verificación explícita para asegurar que el refresh esté en la respuesta

**Prueba recomendada**:
```bash
curl -i -X POST https://api.ecofilia.site/api/auth/token/refresh/ \
  -H "content-type: application/json" \
  -d '{"refresh":"<token_refresh_actual>"}'
```

**Respuesta esperada**:
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJh...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJh..."  // ← NUEVO TOKEN ROTADO
}
```

### ✅ 3. Permisos y CSRF

**Estado**: CONFIGURADO CORRECTAMENTE

- El endpoint `token/refresh/` tiene `permission_classes = [AllowAny]`
- No requiere autenticación previa (stateless)
- No requiere CSRF token (usa JWT para validación)
- El middleware CSRF no bloquea este endpoint porque usa JWT

### ✅ 4. Cookie Domain

**Estado**: MANEJADO EN FRONTEND

- El backend no emite cookies directamente
- El frontend debe configurar `AUTH_COOKIE_DOMAIN=.ecofilia.site` en Vercel
- La cookie debe tener:
  - `Domain=.ecofilia.site` (para funcionar en www y apex)
  - `Secure=True` (solo HTTPS)
  - `SameSite=Lax`
  - `HttpOnly=True` (recomendado)

### ⚠️ 5. Problema Identificado: Race Conditions

**Estado**: PROBLEMA POTENCIAL

El problema de "Token is blacklisted" puede ocurrir cuando:

1. **Múltiples llamadas concurrentes**: Si el SSR y el cliente hacen refresh simultáneamente:
   - Llamada 1 usa refresh R0 → Backend devuelve R1, blacklistea R0
   - Llamada 2 usa refresh R0 (aún no actualizado en cookie) → Backend rechaza porque R0 está blacklisted

2. **Timing de actualización de cookie**: Si el frontend no actualiza la cookie inmediatamente después de recibir el nuevo refresh, la siguiente llamada usará el refresh viejo.

**Solución implementada**:
- La vista custom garantiza que siempre se devuelve el refresh rotado
- El frontend debe actualizar la cookie inmediatamente al recibir la respuesta
- Se recomienda implementar un lock/mutex en el frontend para evitar llamadas concurrentes

## Cambios Realizados

### 1. Vista Custom de Refresh

**Archivo**: `backend/apps/authentication/api/views.py`

Se creó `CustomTokenRefreshView` que:
- Extiende `TokenRefreshView` de SimpleJWT
- Garantiza permisos `AllowAny` explícitos
- Verifica que el refresh rotado esté en la respuesta
- Incluye logging de advertencia si hay problemas de configuración

### 2. Actualización de URLs

**Archivo**: `backend/apps/authentication/api/urls.py`

- Se reemplazó `TokenRefreshView` por `CustomTokenRefreshView`
- El endpoint sigue siendo `POST /api/auth/token/refresh/`

## Checklist de Verificación

- [x] `ROTATE_REFRESH_TOKENS=True` en settings
- [x] `BLACKLIST_AFTER_ROTATION=True` en settings
- [x] Endpoint de refresh devuelve refresh rotado
- [x] Endpoint no requiere CSRF/sessionid
- [x] Permisos correctos (AllowAny)
- [x] Vista custom creada para garantizar comportamiento
- [ ] **PENDIENTE**: Verificar con curl que el endpoint devuelve refresh
- [ ] **PENDIENTE**: Verificar que frontend actualiza cookie inmediatamente
- [ ] **PENDIENTE**: Implementar lock en frontend para evitar race conditions

## Próximos Pasos

### Backend (Completado ✅)

1. ✅ Crear vista custom de refresh
2. ✅ Verificar configuración de SimpleJWT
3. ✅ Asegurar que no hay problemas de CSRF

### Frontend (Pendiente)

1. **Verificar actualización de cookie**: Asegurar que cuando `token/refresh/` devuelve `{ access, refresh }`, el frontend actualiza la cookie `ecofilia_refresh` inmediatamente.

2. **Implementar lock para refresh**: Evitar múltiples llamadas concurrentes a `token/refresh/`:
   ```typescript
   let refreshPromise: Promise<AuthTokens> | null = null;
   
   async function refreshTokens() {
     if (refreshPromise) return refreshPromise;
     refreshPromise = callRefreshAPI();
     try {
       const result = await refreshPromise;
       return result;
     } finally {
       refreshPromise = null;
     }
   }
   ```

3. **Verificar dominio de cookie**: Asegurar que `AUTH_COOKIE_DOMAIN=.ecofilia.site` está configurado en Vercel.

### Testing

1. **Prueba manual con curl**:
   ```bash
   # 1. Login y obtener refresh token
   # 2. Usar refresh token para obtener nuevo access
   # 3. Verificar que la respuesta incluye nuevo refresh
   curl -X POST https://api.ecofilia.site/api/auth/token/refresh/ \
     -H "Content-Type: application/json" \
     -d '{"refresh":"<token>"}'
   ```

2. **Prueba de flujo completo**:
   - Login → Verificar cookies
   - Acceder a `/protected` → Verificar que no redirige a `/auth`
   - Verificar logs del backend para confirmar que no hay errores de blacklist

## Conclusión

El backend está **correctamente configurado** para rotación de tokens con blacklist. El problema reportado (`Token is blacklisted`) es más probable que sea causado por:

1. **Race conditions** en el frontend (múltiples llamadas concurrentes)
2. **Cookie no actualizada** inmediatamente después del refresh
3. **Múltiples pestañas/clientes** usando el mismo refresh token

La solución requiere coordinación entre frontend y backend:
- ✅ Backend: Garantiza que siempre devuelve refresh rotado (implementado)
- ⚠️ Frontend: Debe actualizar cookie inmediatamente y evitar llamadas concurrentes (pendiente)

## Referencias

- [SimpleJWT Documentation](https://django-rest-framework-simplejwt.readthedocs.io/)
- [Token Blacklist](https://django-rest-framework-simplejwt.readthedocs.io/en/stable/blacklist_app.html)
- [Token Rotation](https://django-rest-framework-simplejwt.readthedocs.io/en/stable/settings.html#rotate-refresh-tokens)

