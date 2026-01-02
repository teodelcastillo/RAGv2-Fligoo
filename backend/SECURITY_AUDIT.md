# Auditoría de Seguridad - Autenticación y Tokens (Backend)

## Fecha: 2026-01-02

## Resumen Ejecutivo

Se revisó la capa de autenticación basada en DRF + SimpleJWT, con énfasis en el endpoint de refresh (`CustomTokenRefreshView`) y los controles complementarios (MFA, verificación de email, rate limiting, gestión de contraseñas y cabeceras de seguridad). La implementación actual alinea buenas prácticas y es apta para producción, siempre que se apliquen las configuraciones indicadas.

## Alcance y Contexto

- Framework: Django 5 + DRF.
- Autenticación: JWT con `rest_framework_simplejwt` (rotación y blacklist habilitados).
- Usuario: modelo custom (`apps.user.models.User`) con campos de seguridad (`email_verified`, `mfa_enabled`, `role`, `last_password_change`).
- Endpoints clave: login con MFA (`TokenObtainPairWithMFAView`), refresh (`CustomTokenRefreshView`), logout (blacklist), recuperación y cambio de contraseña, setup/verify/disable MFA, verificación de email.
- Configuración central: `main/settings/base.py` y `apps/authentication/api/views.py`.

## Hallazgos Positivos

1. **Rotación y revocación de refresh tokens**
   - `ROTATE_REFRESH_TOKENS=True` y `BLACKLIST_AFTER_ROTATION=True`.
   - Chequeo explícito para garantizar que el nuevo refresh se devuelva cuando la rotación está activa; loguea cualquier desalineación sin exponer datos.

2. **Rate limiting defensivo**
   - Throttling global: `anon` 30/min, `user` 120/min (configurable por env).
   - Throttle específico para refresh: `StrictRefreshThrottle` (`strict_refresh` 20/min por defecto), más estricto que el general.

3. **Controles de autenticación**
   - Login bloquea usuarios sin email verificado.
   - MFA TOTP opcional: exige OTP cuando está habilitado y registra intentos inválidos.
   - Logout invalida refresh tokens mediante blacklist.

4. **Gestión de contraseñas**
   - Validadores de Django activos (longitud, similitud, común, numérica).
   - `last_password_change` se actualiza automáticamente; se fuerza MFA a off y se limpian secretos en reset.

5. **Cabeceras y cookies seguras**
   - `SESSION_COOKIE_HTTPONLY=True`, `CSRF_COOKIE_HTTPONLY=True`, `SAMESITE=Lax` por defecto (configurable).
   - `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` y HSTS configurables por env.
   - `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY="same-origin"`, `SECURE_CONTENT_TYPE_NOSNIFF=True`, `SECURE_BROWSER_XSS_FILTER=True`.

6. **CORS y exposición controlada**
   - Lista blanca configurable por env; credenciales permitidas solo para orígenes definidos.

7. **Logging seguro**
   - Logging centralizado sin tokens; trazas completas solo en `DEBUG`.
   - Eventos relevantes: login, MFA requerido/incorrecto, refresh exitoso/fallido.

8. **Tests automáticos**
   - Cobertura de flujos críticos: registro (envío de email), login con verificación de email, MFA, reset de contraseña, cambio de contraseña.

## Detalle por Componente

### JWT y Sesiones
- Access TTL: `JWT_ACCESS_TTL_MINUTES` (default 15m).
- Refresh TTL: `JWT_REFRESH_TTL_DAYS` (default 7d).
- Algoritmo: `HS256` con clave dedicada `JWT_SIGNING_KEY` (separada de `SECRET_KEY`).
- `AUTH_HEADER_TYPES=("Bearer",)`, `UPDATE_LAST_LOGIN=True`.

### Endpoint de Refresh (`token/refresh/`)
- Permisos: `AllowAny` (correcto para flujo stateless).
- Throttle: `StrictRefreshThrottle` (`strict_refresh`).
- Seguridad en código:
  - Serializador de SimpleJWT con validación estándar de expiración/estructura.
  - Chequeo de presencia de `refresh` cuando la rotación está activa; loguea error y sigue devolviendo el access para no romper cliente.
  - Manejo de excepciones: registra clase del error, sin detalles sensibles; traza completa solo en `DEBUG`.

### Login (`login/`)
- Verifica `email_verified`; si no, devuelve `401 email_not_verified`.
- Si `mfa_enabled`, exige `otp`; en ausencia o error devuelve `401 mfa_required/mfa_invalid`.
- Devuelve `user` (perfil) junto a `access` y `refresh`.

### Logout (`logout/`)
- Permite solo usuarios autenticados; blacklistea el refresh enviado. Responde `204` (sin detalle) para no filtrar estado interno.

### Gestión de contraseñas
- **Reset**: token seguro de Django (`PasswordResetTokenGenerator`), UID codificado; al resetear se desactiva MFA y se limpia secreto.
- **Change**: requiere autenticación y valida `old_password`; aplica validadores de complejidad.

### MFA (TOTP)
- Endpoints para generar secreto y QR (`mfa/setup/`), verificar (`mfa/verify/`) y desactivar (`mfa/disable/`).
- Usa `django_otp` y `pyotp` para verificación; registra intentos inválidos.

### Modelo de Usuario y Roles
- Roles (`admin`, `manager`, `member`) para asignación de permisos por defecto.
- Campos de seguridad: `email_verified`, `email_verified_at`, `mfa_enabled`, `mfa_secret`, `last_password_change`.

### Middleware y Superficie de Exposición
- `CsrfViewMiddleware` activo (para endpoints no stateless).
- `corsheaders.middleware.CorsMiddleware` antes de seguridad.
- `SECURE_PROXY_SSL_HEADER` configurado para despliegues detrás de proxy/ELB.

## Riesgos Residuales y Mitigaciones Recomendadas

- **Concurrency en frontend**: aplicar mutex/lock en cliente para no disparar múltiples refresh concurrentes con el mismo token.
- **Transporte**: exigir HTTPS extremo a extremo (`SECURE_SSL_REDIRECT=True`, HSTS>0) y bloquear HTTP en infraestructura.
- **Cookies en frontend**: si se usan, marcarlas `HttpOnly`, `Secure`, `SameSite=Lax` y dominio correcto.
- **Almacenamiento de tokens en frontend**: evitar `localStorage`; preferir cookies seguras o memory storage con rotación frecuente.
- **Monitoreo**: alertar picos de `strict_refresh` throttling, MFA inválido recurrente y resets de contraseña inusuales.
- **Gestión de claves**: mantener `JWT_SIGNING_KEY` diferente a `SECRET_KEY`, rotarla bajo control y almacenarla en KMS/Secrets Manager.

## Checklist de Configuración para Producción

- `DEBUG=False`
- `SECRET_KEY` y `JWT_SIGNING_KEY` fuertes y distintas.
- `JWT_ACCESS_TTL_MINUTES=15`, `JWT_REFRESH_TTL_DAYS=7` (ajustar según riesgo).
- `DRF_THROTTLE_RATE_REFRESH=20/min` (o más estricto si es necesario).
- `SECURE_SSL_REDIRECT=True`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`, `SECURE_HSTS_SECONDS>0`.
- `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE` configuradas según dominio frontend.
- `ALLOWED_HOSTS` y `CORS_ALLOWED_ORIGINS` definidos a dominios esperados.
- Credenciales SMTP y URLs frontend (`FRONTEND_BASE_URL`) configuradas para emails de verificación/reset.

## Conclusión

La implementación actual cumple con prácticas recomendadas de seguridad para APIs JWT: rotación y blacklist de refresh tokens, rate limiting específico, enforcement de verificación de email y MFA opcional, controles de cabeceras y cookies, y pruebas automatizadas de los flujos críticos. Con las variables anteriores correctamente definidas y HTTPS obligatorio, el nivel de seguridad es **ALTO** y apto para entornos productivos.

## Referencias

- [OWASP JWT Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html)
- [Django REST Framework Security](https://www.django-rest-framework.org/topics/security/)
- [SimpleJWT Best Practices](https://django-rest-framework-simplejwt.readthedocs.io/)