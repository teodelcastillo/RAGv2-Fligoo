# Guía Rápida: Autenticación Next.js en Vercel

## Checklist de Implementación

### 1. Variables de Entorno en Vercel

Ve a **Vercel Dashboard → Tu Proyecto → Settings → Environment Variables** y agrega:

```bash
NEXT_PUBLIC_API_URL=https://api.ecofilia.site
NEXT_PUBLIC_BACKEND_URL=https://api.ecofilia.site
AUTH_COOKIE_DOMAIN=.ecofilia.site
AUTH_COOKIE_NAME=ecofilia_refresh
AUTH_COOKIE_MAX_AGE=604800
```

**⚠️ IMPORTANTE**: El dominio debe empezar con punto (`.ecofilia.site`) para funcionar en `www.ecofilia.site` y `ecofilia.site`.

### 2. Estructura Mínima de Archivos

Crea estos archivos en tu proyecto Next.js:

```
lib/auth/
├── types.ts                    # Tipos TypeScript
├── cookie-utils.ts            # Funciones para cookies
└── auth-service.ts            # Lógica de autenticación

app/api/internal/auth/
├── session/route.ts           # GET /api/internal/auth/session
└── token/refresh/route.ts     # POST /api/internal/auth/token/refresh

app/middleware.ts              # Protección de rutas
```

### 3. Puntos Críticos de Implementación

#### ✅ Rotación de Tokens (CRÍTICO)

Cuando el backend devuelve `{ access, refresh }` después de un refresh:

```typescript
// ✅ CORRECTO: Actualizar cookie inmediatamente
if (tokens.refresh) {
  setRefreshCookie(tokens.refresh);
}

// ❌ INCORRECTO: No actualizar la cookie
// Esto causará "Token is blacklisted" en la siguiente llamada
```

#### ✅ Lock para Evitar Race Conditions

```typescript
let refreshPromise: Promise<AuthTokens> | null = null;

export async function refreshTokens(): Promise<AuthTokens> {
  // Si ya hay una llamada en progreso, reutilizar su resultado
  if (refreshPromise) {
    return refreshPromise;
  }
  
  refreshPromise = (async () => {
    try {
      // ... lógica de refresh ...
      return tokens;
    } finally {
      refreshPromise = null; // Limpiar lock
    }
  })();
  
  return refreshPromise;
}
```

#### ✅ Cookie HTTP-Only

```typescript
cookies().set(COOKIE_NAME, token, {
  httpOnly: true,              // ✅ No accesible desde JavaScript
  secure: process.env.NODE_ENV === 'production',  // ✅ Solo HTTPS en prod
  sameSite: 'lax',             // ✅ Protección CSRF
  domain: '.ecofilia.site',     // ✅ Funciona en subdominios
  maxAge: 604800,              // ✅ 7 días
  path: '/',
});
```

### 4. Flujo de Sesión en SSR

Para páginas protegidas que usan Server Components:

```typescript
// app/(protected)/protected/page.tsx
import { getSession } from '@/lib/auth/auth-service';
import { redirect } from 'next/navigation';

export default async function ProtectedPage() {
  const session = await getSession();
  
  if (!session) {
    redirect('/auth/login?redirect=/protected');
  }
  
  return <div>Bienvenido {session.user.first_name}</div>;
}
```

### 5. Middleware para Protección Global

```typescript
// app/middleware.ts
export async function middleware(request: NextRequest) {
  const isProtectedRoute = pathname.startsWith('/protected');
  
  if (isProtectedRoute) {
    const sessionResponse = await fetch(
      new URL('/api/internal/auth/session', request.url),
      { headers: { cookie: request.headers.get('cookie') || '' } }
    );
    
    if (!sessionResponse.ok) {
      return NextResponse.redirect(new URL('/auth/login', request.url));
    }
  }
  
  return NextResponse.next();
}
```

### 6. Verificación Post-Deploy

Después de desplegar en Vercel:

1. **Login y verificar cookie**:
   - Abre DevTools → Application → Cookies
   - Busca `ecofilia_refresh`
   - Verifica: `Domain=.ecofilia.site`, `Secure`, `HttpOnly`, `SameSite=Lax`

2. **Probar navegación protegida**:
   - Login → Navegar a `/protected`
   - No debe redirigir a `/auth/login`
   - Debe mostrar contenido protegido

3. **Probar refresh automático**:
   - Esperar 15 min o forzar refresh
   - La sesión debe mantenerse
   - Cookie debe actualizarse con nuevo refresh token

### 7. Troubleshooting Común

#### Error: "Token is blacklisted"

**Causa**: Cookie no se actualiza después del refresh o llamadas concurrentes.

**Solución**:
- Verificar que `setRefreshCookie()` se llama inmediatamente después de recibir `tokens.refresh`
- Verificar que el lock está funcionando en `refreshTokens()`
- Revisar logs del backend para confirmar que devuelve refresh rotado

#### Error: Cookie no se guarda

**Causa**: Dominio incorrecto o configuración de cookie.

**Solución**:
- Verificar `AUTH_COOKIE_DOMAIN=.ecofilia.site` (con punto inicial)
- Asegurar que el dominio coincide con el dominio de la app
- En producción, `Secure=true` requiere HTTPS

#### Redirección infinita

**Causa**: Middleware o verificación de sesión incorrecta.

**Solución**:
- Verificar que `/api/internal/auth/session` responde 200 cuando hay sesión válida
- Revisar lógica del middleware
- Asegurar que las rutas están correctamente configuradas

### 8. Código de Ejemplo Completo

Ver `FRONTEND_AUTH_IMPLEMENTATION_GUIDE.md` para código completo de todos los archivos.

## Resumen de Flujo

```
1. Usuario hace login
   ↓
2. Backend devuelve { access, refresh, user }
   ↓
3. Frontend guarda refresh en cookie HTTP-only
   ↓
4. Frontend usa access token para requests protegidos
   ↓
5. Si access expira → Frontend llama refresh automáticamente
   ↓
6. Backend rota refresh → Devuelve nuevo { access, refresh }
   ↓
7. Frontend actualiza cookie con nuevo refresh inmediatamente
   ↓
8. Usuario puede seguir navegando sin interrupciones
```

## Próximos Pasos

1. ✅ Implementar archivos según la guía completa
2. ✅ Configurar variables de entorno en Vercel
3. ✅ Desplegar y verificar cookies
4. ✅ Probar flujo completo de autenticación
5. ✅ Monitorear logs para detectar problemas

¡Listo para producción! 🚀


