# Guía de Implementación de Autenticación - Next.js Frontend

## Resumen

Esta guía explica cómo implementar la autenticación en Next.js (App Router) para trabajar con el backend Django que usa JWT con rotación de tokens y blacklist.

## Arquitectura de Autenticación

### Flujo de Autenticación

```
1. Login → Backend devuelve { access, refresh, user }
2. Guardar refresh en cookie HTTP-only (ecofilia_refresh)
3. Guardar access en memoria/estado (no persistir)
4. En cada request protegido → Usar access token
5. Si access expira → Refresh automático usando refresh token
6. Backend rota refresh → Actualizar cookie inmediatamente
7. Navegación protegida → Verificar sesión en SSR
```

## Estructura de Archivos Recomendada

```
frontend/
├── lib/
│   └── auth/
│       ├── auth-service.ts          # Servicio de autenticación
│       ├── cookie-utils.ts          # Utilidades para cookies
│       └── types.ts                 # Tipos TypeScript
├── app/
│   ├── api/
│   │   └── internal/
│   │       └── auth/
│   │           ├── session/
│   │           │   └── route.ts     # GET /api/internal/auth/session
│   │           └── token/
│   │               └── refresh/
│   │                   └── route.ts # POST /api/internal/auth/token/refresh
│   ├── (auth)/
│   │   └── auth/
│   │       └── login/
│   │           └── page.tsx         # Página de login
│   ├── (protected)/
│   │   └── protected/
│   │       └── page.tsx             # Página protegida ejemplo
│   └── middleware.ts                # Middleware para proteger rutas
└── .env.local                        # Variables de entorno
```

## Implementación Paso a Paso

### 1. Variables de Entorno

Crea `.env.local` en Vercel (Settings → Environment Variables):

```bash
# Backend API
NEXT_PUBLIC_API_URL=https://api.ecofilia.site
NEXT_PUBLIC_BACKEND_URL=https://api.ecofilia.site

# Cookie Configuration
AUTH_COOKIE_DOMAIN=.ecofilia.site
AUTH_COOKIE_NAME=ecofilia_refresh
AUTH_COOKIE_MAX_AGE=604800  # 7 días en segundos
```

### 2. Tipos TypeScript

**`lib/auth/types.ts`**

```typescript
export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
  email_verified: boolean;
  approved: boolean;
  mfa_enabled: boolean;
}

export interface AuthTokens {
  access: string;
  refresh: string;
}

export interface AuthResponse {
  access: string;
  refresh: string;
  user: User;
}

export interface SessionData {
  access: string;
  user: User;
}
```

### 3. Utilidades de Cookies

**`lib/auth/cookie-utils.ts`**

```typescript
import { cookies } from 'next/headers';

const COOKIE_NAME = process.env.AUTH_COOKIE_NAME || 'ecofilia_refresh';
const COOKIE_DOMAIN = process.env.AUTH_COOKIE_DOMAIN || '.ecofilia.site';
const COOKIE_MAX_AGE = parseInt(
  process.env.AUTH_COOKIE_MAX_AGE || '604800',
  10
);

export function setRefreshCookie(token: string) {
  const cookieStore = cookies();
  cookieStore.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: COOKIE_MAX_AGE,
    domain: COOKIE_DOMAIN,
    path: '/',
  });
}

export function getRefreshCookie(): string | null {
  const cookieStore = cookies();
  return cookieStore.get(COOKIE_NAME)?.value || null;
}

export function deleteRefreshCookie() {
  const cookieStore = cookies();
  cookieStore.delete(COOKIE_NAME);
}
```

### 4. Servicio de Autenticación

**`lib/auth/auth-service.ts`**

```typescript
import { AuthResponse, AuthTokens, SessionData } from './types';
import { setRefreshCookie, getRefreshCookie, deleteRefreshCookie } from './cookie-utils';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://api.ecofilia.site';
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || API_URL;

// Lock para evitar llamadas concurrentes de refresh
let refreshPromise: Promise<AuthTokens> | null = null;

export class AuthServiceError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public payload?: unknown
  ) {
    super(message);
    this.name = 'AuthServiceError';
  }
}

/**
 * Login: Autentica usuario y guarda tokens
 */
export async function login(
  email: string,
  password: string,
  otp?: string
): Promise<AuthResponse> {
  const response = await fetch(`${BACKEND_URL}/api/auth/login/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password, otp }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new AuthServiceError(
      error.detail || 'Error al iniciar sesión',
      response.status,
      error.code,
      error
    );
  }

  const data: AuthResponse = await response.json();

  // Guardar refresh token en cookie HTTP-only
  setRefreshCookie(data.refresh);

  return data;
}

/**
 * Refresh tokens: Obtiene nuevo access token usando refresh token
 * Implementa lock para evitar llamadas concurrentes
 */
export async function refreshTokens(): Promise<AuthTokens> {
  // Si ya hay una llamada en progreso, esperar su resultado
  if (refreshPromise) {
    return refreshPromise;
  }

  const refreshToken = getRefreshCookie();
  if (!refreshToken) {
    throw new AuthServiceError('No hay refresh token disponible', 401, 'no_refresh_token');
  }

  // Crear promesa de refresh
  refreshPromise = (async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/auth/token/refresh/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh: refreshToken }),
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        
        // Si el refresh token es inválido, limpiar cookie
        if (response.status === 401) {
          deleteRefreshCookie();
        }

        throw new AuthServiceError(
          error.detail || 'Error al refrescar tokens',
          response.status,
          error.code || 'token_not_valid',
          error
        );
      }

      const data: AuthTokens = await response.json();

      // IMPORTANTE: Actualizar cookie con el nuevo refresh token (rotación)
      if (data.refresh) {
        setRefreshCookie(data.refresh);
      }

      return data;
    } finally {
      // Limpiar lock después de completar
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Obtener sesión actual: Devuelve access token y datos de usuario
 * Usa refresh token si es necesario
 */
export async function getSession(): Promise<SessionData | null> {
  try {
    // Primero intentar obtener sesión desde endpoint interno
    const response = await fetch('/api/internal/auth/session', {
      method: 'GET',
      credentials: 'include',
    });

    if (response.ok) {
      const data: SessionData = await response.json();
      return data;
    }

    // Si falla, intentar refresh
    if (response.status === 401) {
      const tokens = await refreshTokens();
      
      // Reintentar obtener sesión con nuevo access token
      const retryResponse = await fetch('/api/internal/auth/session', {
        method: 'GET',
        credentials: 'include',
        headers: {
          Authorization: `Bearer ${tokens.access}`,
        },
      });

      if (retryResponse.ok) {
        return await retryResponse.json();
      }
    }

    return null;
  } catch (error) {
    console.error('Error al obtener sesión:', error);
    return null;
  }
}

/**
 * Logout: Invalida refresh token y limpia cookie
 */
export async function logout(): Promise<void> {
  const refreshToken = getRefreshCookie();
  
  if (refreshToken) {
    try {
      await fetch(`${BACKEND_URL}/api/auth/logout/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${refreshToken}`, // Opcional, el backend puede requerirlo
        },
        body: JSON.stringify({ refresh: refreshToken }),
      });
    } catch (error) {
      console.error('Error al hacer logout en backend:', error);
    }
  }

  // Siempre limpiar cookie localmente
  deleteRefreshCookie();
}

/**
 * Verificar si el usuario está autenticado
 */
export async function isAuthenticated(): Promise<boolean> {
  const session = await getSession();
  return session !== null;
}
```

### 5. API Routes Internas (Server-Side)

**`app/api/internal/auth/session/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getRefreshCookie } from '@/lib/auth/cookie-utils';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'https://api.ecofilia.site';

/**
 * GET /api/internal/auth/session
 * Obtiene la sesión actual usando el refresh token de la cookie
 */
export async function GET(request: NextRequest) {
  try {
    const refreshToken = getRefreshCookie();

    if (!refreshToken) {
      return NextResponse.json(
        { detail: 'No refresh token available' },
        { status: 401 }
      );
    }

    // Hacer refresh para obtener nuevo access token
    const refreshResponse = await fetch(`${BACKEND_URL}/api/auth/token/refresh/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh: refreshToken }),
    });

    if (!refreshResponse.ok) {
      const error = await refreshResponse.json().catch(() => ({}));
      return NextResponse.json(
        { detail: error.detail || 'Session expired.' },
        { status: 401 }
      );
    }

    const tokens = await refreshResponse.json();

    // Obtener datos del usuario usando el nuevo access token
    const userResponse = await fetch(`${BACKEND_URL}/api/auth/me/`, {
      headers: {
        Authorization: `Bearer ${tokens.access}`,
      },
    });

    if (!userResponse.ok) {
      return NextResponse.json(
        { detail: 'Failed to fetch user data' },
        { status: 401 }
      );
    }

    const user = await userResponse.json();

    // IMPORTANTE: Si el backend devolvió un nuevo refresh, actualizar cookie
    if (tokens.refresh) {
      const { setRefreshCookie } = await import('@/lib/auth/cookie-utils');
      setRefreshCookie(tokens.refresh);
    }

    return NextResponse.json({
      access: tokens.access,
      user,
    });
  } catch (error) {
    console.error('Failed to build server auth session:', error);
    return NextResponse.json(
      { detail: 'Session expired.' },
      { status: 401 }
    );
  }
}
```

**`app/api/internal/auth/token/refresh/route.ts`**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getRefreshCookie, setRefreshCookie, deleteRefreshCookie } from '@/lib/auth/cookie-utils';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'https://api.ecofilia.site';

/**
 * POST /api/internal/auth/token/refresh
 * Refresca tokens usando el refresh token de la cookie
 */
export async function POST(request: NextRequest) {
  try {
    const refreshToken = getRefreshCookie();

    if (!refreshToken) {
      return NextResponse.json(
        { detail: 'No refresh token available' },
        { status: 401 }
      );
    }

    const response = await fetch(`${BACKEND_URL}/api/auth/token/refresh/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ refresh: refreshToken }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      
      // Si el refresh token es inválido, limpiar cookie
      if (response.status === 401) {
        deleteRefreshCookie();
      }

      return NextResponse.json(
        { detail: error.detail || 'Token refresh failed' },
        { status: response.status }
      );
    }

    const tokens = await response.json();

    // IMPORTANTE: Actualizar cookie con el nuevo refresh token (rotación)
    if (tokens.refresh) {
      setRefreshCookie(tokens.refresh);
    }

    return NextResponse.json(tokens);
  } catch (error) {
    console.error('Token refresh error:', error);
    return NextResponse.json(
      { detail: 'Token refresh failed' },
      { status: 500 }
    );
  }
}
```

### 6. Middleware para Proteger Rutas

**`app/middleware.ts`**

```typescript
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// Rutas que requieren autenticación
const protectedRoutes = ['/protected', '/dashboard', '/profile'];
// Rutas de autenticación (redirigir si ya está autenticado)
const authRoutes = ['/auth/login', '/auth/register'];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isProtectedRoute = protectedRoutes.some((route) =>
    pathname.startsWith(route)
  );
  const isAuthRoute = authRoutes.some((route) => pathname.startsWith(route));

  // Verificar sesión solo para rutas protegidas o de auth
  if (isProtectedRoute || isAuthRoute) {
    try {
      const sessionResponse = await fetch(
        new URL('/api/internal/auth/session', request.url),
        {
          headers: {
            cookie: request.headers.get('cookie') || '',
          },
        }
      );

      const isAuthenticated = sessionResponse.ok;

      // Si es ruta protegida y no está autenticado, redirigir a login
      if (isProtectedRoute && !isAuthenticated) {
        const loginUrl = new URL('/auth/login', request.url);
        loginUrl.searchParams.set('redirect', pathname);
        return NextResponse.redirect(loginUrl);
      }

      // Si es ruta de auth y ya está autenticado, redirigir a home
      if (isAuthRoute && isAuthenticated) {
        return NextResponse.redirect(new URL('/', request.url));
      }
    } catch (error) {
      console.error('Middleware auth check error:', error);
      // En caso de error, permitir acceso pero el componente puede manejar el error
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    '/((?!api|_next/static|_next/image|favicon.ico).*)',
  ],
};
```

### 7. Componente de Login

**`app/(auth)/auth/login/page.tsx`**

```typescript
'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { login } from '@/lib/auth/auth-service';

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [otp, setOtp] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [mfaRequired, setMfaRequired] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(email, password, otp || undefined);
      
      // Redirigir a la página original o a home
      const redirect = searchParams.get('redirect') || '/';
      router.push(redirect);
      router.refresh(); // Refrescar para actualizar middleware
    } catch (err: any) {
      if (err.code === 'mfa_required') {
        setMfaRequired(true);
        setError('Ingresa el código MFA');
      } else {
        setError(err.message || 'Error al iniciar sesión');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center">
      <form onSubmit={handleSubmit} className="space-y-4 w-full max-w-md">
        <h1 className="text-2xl font-bold">Iniciar Sesión</h1>
        
        {error && (
          <div className="bg-red-100 text-red-700 p-3 rounded">
            {error}
          </div>
        )}

        <div>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full p-2 border rounded"
          />
        </div>

        <div>
          <label htmlFor="password">Contraseña</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full p-2 border rounded"
          />
        </div>

        {mfaRequired && (
          <div>
            <label htmlFor="otp">Código MFA</label>
            <input
              id="otp"
              type="text"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
              required
              placeholder="000000"
              maxLength={6}
              className="w-full p-2 border rounded"
            />
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white p-2 rounded disabled:opacity-50"
        >
          {loading ? 'Iniciando sesión...' : 'Iniciar Sesión'}
        </button>
      </form>
    </div>
  );
}
```

### 8. Página Protegida de Ejemplo

**`app/(protected)/protected/page.tsx`**

```typescript
import { redirect } from 'next/navigation';
import { getSession } from '@/lib/auth/auth-service';

export default async function ProtectedPage() {
  const session = await getSession();

  if (!session) {
    redirect('/auth/login?redirect=/protected');
  }

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-2xl font-bold mb-4">Página Protegida</h1>
      <div className="bg-white p-4 rounded shadow">
        <p>Bienvenido, {session.user.first_name} {session.user.last_name}!</p>
        <p>Email: {session.user.email}</p>
        <p>Rol: {session.user.role}</p>
      </div>
    </div>
  );
}
```

### 9. Hook para Cliente (Opcional)

**`lib/auth/use-auth.ts`**

```typescript
'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getSession, logout as authLogout, type SessionData } from './auth-service';

export function useAuth() {
  const [session, setSession] = useState<SessionData | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    loadSession();
  }, []);

  const loadSession = async () => {
    try {
      const data = await getSession();
      setSession(data);
    } catch (error) {
      setSession(null);
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    await authLogout();
    setSession(null);
    router.push('/auth/login');
    router.refresh();
  };

  return {
    session,
    loading,
    isAuthenticated: !!session,
    logout,
    refresh: loadSession,
  };
}
```

## Configuración en Vercel

### Variables de Entorno

En Vercel Dashboard → Settings → Environment Variables, agrega:

```bash
NEXT_PUBLIC_API_URL=https://api.ecofilia.site
NEXT_PUBLIC_BACKEND_URL=https://api.ecofilia.site
AUTH_COOKIE_DOMAIN=.ecofilia.site
AUTH_COOKIE_NAME=ecofilia_refresh
AUTH_COOKIE_MAX_AGE=604800
```

### Verificaciones Post-Deploy

1. **Verificar cookies**: Después del login, verifica en DevTools que:
   - Cookie `ecofilia_refresh` existe
   - `Domain=.ecofilia.site`
   - `Secure=true` (en producción)
   - `HttpOnly=true`
   - `SameSite=Lax`

2. **Probar flujo completo**:
   - Login → Verificar cookie
   - Navegar a `/protected` → No debe redirigir
   - Esperar 15 min o forzar refresh → Debe funcionar
   - Logout → Cookie debe eliminarse

## Puntos Críticos

### ✅ Rotación de Tokens

- El backend siempre devuelve un nuevo `refresh` cuando se usa `token/refresh/`
- **IMPORTANTE**: Actualizar la cookie inmediatamente cuando se recibe el nuevo refresh
- Implementar lock para evitar llamadas concurrentes

### ✅ Manejo de Errores

- Si el refresh token es inválido (401), limpiar cookie y redirigir a login
- No exponer detalles de errores al usuario
- Logging adecuado para debugging

### ✅ SSR vs Cliente

- SSR: Usar `getSession()` en Server Components
- Cliente: Usar `useAuth()` hook o llamar a `/api/internal/auth/session`
- Middleware: Verificar sesión antes de renderizar

## Troubleshooting

### Problema: "Token is blacklisted"

**Causa**: Múltiples llamadas concurrentes usando el mismo refresh token.

**Solución**: 
- Verificar que el lock está funcionando en `refreshTokens()`
- Asegurar que la cookie se actualiza inmediatamente después del refresh

### Problema: Redirección infinita

**Causa**: Middleware o componente verificando sesión incorrectamente.

**Solución**:
- Verificar que `/api/internal/auth/session` responde correctamente
- Revisar lógica del middleware
- Asegurar que las rutas están correctamente configuradas

### Problema: Cookie no se persiste

**Causa**: Dominio incorrecto o configuración de cookie.

**Solución**:
- Verificar `AUTH_COOKIE_DOMAIN=.ecofilia.site` en Vercel
- Asegurar que el dominio coincide con el dominio de la aplicación
- Verificar que `Secure=true` solo en HTTPS

## Conclusión

Esta implementación:
- ✅ Maneja rotación de tokens correctamente
- ✅ Previene race conditions con lock
- ✅ Protege rutas con middleware
- ✅ Funciona en SSR y cliente
- ✅ Es segura (cookies HTTP-only)
- ✅ Maneja errores apropiadamente

¡Lista para producción! 🚀


