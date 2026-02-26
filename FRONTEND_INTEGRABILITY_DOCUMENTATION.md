# Documentación de Integrabilidad - Ecofilia RAG API

**Propósito:** Este documento describe cada módulo y etapa de la API para que un agente de frontend pueda revisar la integrabilidad con el backend Django.

**Versión:** Febrero 2025  
**Base URL:** `http://localhost` (reemplazar por dominio real en producción)

---

## Índice

1. [Arquitectura General](#1-arquitectura-general)
2. [Autenticación](#2-autenticación)
3. [Módulo Documentos](#3-módulo-documentos)
4. [Módulo Chat](#4-módulo-chat)
5. [Módulo Proyectos](#5-módulo-proyectos)
6. [Módulo Evaluaciones](#6-módulo-evaluaciones)
7. [Módulo Plantillas de Evaluación](#7-módulo-plantillas-de-evaluación)
8. [Modelos de Datos y Tipos](#8-modelos-de-datos-y-tipos)
9. [Flujos de Integración](#9-flujos-de-integración)
10. [Configuración Frontend](#10-configuración-frontend)
11. [Checklist de Integrabilidad](#11-checklist-de-integrabilidad)

---

## 1. Arquitectura General

### 1.1 Estructura de URLs

| Prefijo | Módulo | Descripción |
|--------|--------|-------------|
| `/api/auth/` | Autenticación | Registro, login, JWT, MFA, perfil |
| `/api/document/` | Documentos | CRUD, RAG, subida, listado |
| `/api/chat/` | Chat | Sesiones y mensajes con RAG |
| `/api/projects/` | Proyectos | CRUD, documentos, compartición |
| `/api/evaluations/` | Evaluaciones | Evaluaciones custom, runs, shares |
| `/api/evaluation-templates/` | Plantillas | Plantillas predefinidas (ASG Allen Manza) |

### 1.2 Autenticación Global

**Todas las rutas protegidas** requieren:

```
Authorization: Bearer <access_token>
```

- **Content-Type:** `application/json` para requests con body
- **CORS:** Configurado vía `CORS_ALLOWED_ORIGINS` (ej: `http://localhost:3000`)
- **Tokens:** JWT con rotación de refresh tokens y blacklist

### 1.3 Respuestas de Error Comunes

| Código | Significado | Acción sugerida |
|--------|-------------|-----------------|
| 400 | Bad Request | Revisar payload, validar campos |
| 401 | No autenticado / Token expirado | Refrescar token o redirigir a login |
| 403 | Sin permisos | Mostrar mensaje de acceso denegado |
| 404 | Recurso no encontrado | Verificar slug/ID |
| 429 | Rate limit | Esperar y reintentar |
| 500 | Error interno | Mostrar mensaje genérico |

---

## 2. Autenticación

**Base:** `/api/auth/`

### 2.1 Endpoints

| Método | Path | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/register/` | No | Crear cuenta (email como username) |
| POST | `/verify-email/` | No | Validar email con `uid` + `token` |
| POST | `/login/` | No | Obtener `access` + `refresh` + `user` |
| POST | `/token/refresh/` | No* | Renovar access token |
| POST | `/logout/` | Sí | Blacklistear refresh token |
| GET/PATCH | `/me/` | Sí | Leer/actualizar perfil |
| POST | `/password/change/` | Sí | Cambiar contraseña |
| POST | `/password/reset/` | No | Solicitar reset por email |
| POST | `/password/reset/confirm/` | No | Confirmar nueva contraseña |
| POST | `/mfa/setup/` | Sí | Configurar MFA (TOTP) |
| POST | `/mfa/verify/` | Sí | Verificar código MFA |
| POST | `/mfa/disable/` | Sí | Desactivar MFA |

\* Refresh usa el refresh token en el body, no el header.

### 2.2 Flujo de Login

```
1. POST /api/auth/login/
   Body: { "email": "...", "password": "...", "otp": "123456" }  // otp solo si MFA activo
   
2. Respuesta 200:
   {
     "access": "eyJ0eXAiOiJKV1QiLCJh...",
     "refresh": "eyJ0eXA...",
     "user": {
       "id": 1,
       "email": "user@example.com",
       "first_name": "...",
       "last_name": "...",
       "role": "member",
       "email_verified": true,
       "mfa_enabled": true
     }
   }
```

### 2.3 Flujo de Refresh

```
POST /api/auth/token/refresh/
Body: { "refresh": "<refresh_token>" }

Respuesta 200:
{ "access": "...", "refresh": "..." }  // El refresh puede rotar
```

**Importante:** Guardar el nuevo `refresh` si viene en la respuesta (rotación).

### 2.4 Flujo de Logout

```
POST /api/auth/logout/
Headers: Authorization: Bearer <access_token>
Body: { "refresh": "<refresh_token>" }
```

### 2.5 Tipos TypeScript (Auth)

```typescript
interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: 'admin' | 'manager' | 'member';
  email_verified: boolean;
  approved?: boolean;
  mfa_enabled: boolean;
}

interface AuthResponse {
  access: string;
  refresh: string;
  user: User;
}
```

---

## 3. Módulo Documentos

**Base:** `/api/document/`

### 3.1 Endpoints

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/rag/?query=...` | Búsqueda semántica (RAG) |
| POST | `/create/` | Subir documento (multipart/form-data) |
| POST | `/create/bulk/` | Subida masiva |
| GET | `/list/` | Listar documentos con filtros |
| GET | `/<slug>/` | Detalle de documento |
| PATCH | `/<slug>/` | Actualizar metadata |
| PUT | `/<slug>/` | Actualización completa |
| DELETE | `/<slug>/` | Eliminar documento |

### 3.2 RAG Query

```
GET /api/document/rag/?query=climate+change&documents=doc1&documents=doc2&public=true
```

**Query params:**
- `query` (required): texto de búsqueda
- `documents` (opcional): array de slugs para filtrar
- `public` (opcional): `"true"` o `"false"` para filtrar por visibilidad

**Respuesta 200:**
```json
{
  "query": "climate change",
  "results": [
    {
      "id": 1,
      "content": "...",
      "chunk_index": 0,
      "document_id": 5,
      "token_count": 120,
      "embedding": [0.123, ...],
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### 3.3 Crear Documento

```
POST /api/document/create/
Content-Type: multipart/form-data
Body: file=<archivo>
```

**Respuesta 201:**
```json
{
  "id": 5,
  "slug": "my-document-2024",
  "name": "my-document-2024",
  "category": "",
  "description": "",
  "file": "/media/documents/my-document-2024.pdf",
  "is_public": false,
  "is_owner": true,
  "owner_email": "user@example.com",
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Nota:** El procesamiento (chunking, embeddings) es asíncrono. Usar `chunking_status` para monitorear.

### 3.4 Listar Documentos

```
GET /api/document/list/?name__icontains=report&chunking_status=done&is_public=true
```

**Filtros disponibles:** `slug`, `name`, `category`, `extracted_text__icontains`, `chunking_status`, `created_at`, `is_public`

### 3.5 Detalle y Actualización

- **GET** `/<slug>/`: devuelve documento con `chunking_status`, `chunking_done`, etc.
- **PATCH** `/<slug>/`: campos `name`, `category`, `description`; `is_public` solo superadmins.

### 3.6 Tipos TypeScript (Document)

```typescript
interface Document {
  id: number;
  slug: string;
  name: string;
  category: string;
  description: string;
  file: string;
  is_public: boolean;
  is_owner: boolean;
  owner_email: string;
  created_at: string;
  chunking_status?: 'pending' | 'processing' | 'done' | 'error';
  chunking_done?: boolean;
}
```

---

## 4. Módulo Chat

**Base:** `/api/chat/`

### 4.1 Endpoints

| Método | Path | Descripción |
|--------|------|-------------|
| POST | `/sessions/` | Crear sesión |
| GET | `/sessions/` | Listar sesiones del usuario |
| GET | `/sessions/<id>/` | Detalle de sesión |
| PATCH | `/sessions/<id>/` | Actualizar sesión |
| DELETE | `/sessions/<id>/` | Eliminar sesión |
| POST | `/messages/` | Enviar mensaje y recibir respuesta |

### 4.2 Crear Sesión

```
POST /api/chat/sessions/
Body: {
  "title": "Reporte de sostenibilidad",
  "document_slugs": ["reporte-2024"],
  "system_prompt": "...",
  "model": "gpt-4o-mini",
  "temperature": 0.2,
  "language": "es"
}
```

- `document_slugs`: opcional, puede ser `[]` para chat general sin documentos.
- `system_prompt`, `model`, `temperature`, `language`: opcionales.

**Respuesta 201:**
```json
{
  "id": 5,
  "title": "Reporte de sostenibilidad",
  "system_prompt": "...",
  "model": "gpt-4o-mini",
  "temperature": 0.2,
  "language": "es",
  "is_active": true,
  "created_at": "2025-02-01T13:10:00Z",
  "updated_at": "2025-02-01T13:10:00Z",
  "document_slugs": ["reporte-2024"]
}
```

### 4.3 Enviar Mensaje

```
POST /api/chat/messages/
Body: {
  "session": 5,
  "content": "¿Cuáles son los objetivos principales del reporte?"
}
```

**Respuesta 201:**
```json
{
  "user_message": {
    "id": 12,
    "session": 5,
    "role": "user",
    "content": "...",
    "chunk_ids": [],
    "chunks": [],
    "metadata": {},
    "created_at": "..."
  },
  "assistant_message": {
    "id": 13,
    "session": 5,
    "role": "assistant",
    "content": "El reporte prioriza...",
    "chunk_ids": [45, 47],
    "chunks": [
      {
        "id": 45,
        "document_slug": "reporte-2024",
        "document_name": "Reporte 2024",
        "chunk_index": 3,
        "content": "..."
      }
    ],
    "metadata": { "usage": { "total_tokens": 220 } },
    "created_at": "..."
  }
}
```

### 4.4 Tipos TypeScript (Chat)

```typescript
interface ChatSession {
  id: number;
  title: string;
  system_prompt?: string;
  model: string;
  temperature: number;
  language: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  document_slugs: string[];
}

interface ChatMessage {
  id: number;
  session: number;
  role: 'user' | 'assistant';
  content: string;
  chunk_ids: number[];
  chunks: Array<{ id: number; document_slug: string; document_name: string; chunk_index: number; content: string }>;
  metadata: Record<string, unknown>;
  created_at: string;
}
```

---

## 5. Módulo Proyectos

**Base:** `/api/projects/`

### 5.1 Endpoints (ViewSet REST)

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/` | Listar proyectos |
| POST | `/` | Crear proyecto |
| GET | `/<slug>/` | Detalle |
| PATCH | `/<slug>/` | Actualizar |
| DELETE | `/<slug>/` | Eliminar |
| POST | `/<slug>/documents/` | Añadir documentos |
| DELETE | `/<slug>/documents/` | Quitar documentos |
| GET | `/<slug>/shares/` | Listar shares |
| POST | `/<slug>/shares/` | Añadir share |
| PATCH/DELETE | `/<slug>/shares/<id>/` | Editar/revocar share |

### 5.2 Crear Proyecto

```
POST /api/projects/
Body: {
  "name": "Proyecto Demo",
  "slug": "proyecto-demo",
  "description": "..."
}
```

### 5.3 Añadir Documentos al Proyecto

```
POST /api/projects/<slug>/documents/
Body: { "document_slugs": ["doc-1", "doc-2"] }
```

### 5.4 Compartir Proyecto

```
POST /api/projects/<slug>/shares/
Body: { "user_id": 42, "role": "editor" }
```

**Roles:** `viewer` (solo lectura), `editor` (puede editar y ejecutar).

### 5.5 Permisos

- Usuario ve solo proyectos propios, compartidos con él o públicos.
- `can_edit`: owner o share con rol `editor`.

---

## 6. Módulo Evaluaciones

**Base:** `/api/evaluations/`

### 6.1 Endpoints

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/` | Listar evaluaciones |
| POST | `/` | Crear evaluación |
| GET | `/<slug>/` | Detalle |
| PATCH | `/<slug>/` | Actualizar |
| DELETE | `/<slug>/` | Eliminar |
| GET | `/<slug>/shares/` | Listar shares |
| POST | `/<slug>/shares/` | Añadir share |
| PATCH/DELETE | `/<slug>/shares/<id>/` | Editar/revocar share |
| POST | `/<slug>/runs/` | Ejecutar evaluación |
| GET | `/<slug>/runs/` | Listar runs |
| GET | `/<slug>/runs/<run_id>/` | Detalle de run |

### 6.2 Crear Evaluación

```
POST /api/evaluations/
Body: {
  "title": "Evaluación ESG 2025",
  "visibility": "private",
  "project_slug": "proyecto-demo",
  "document_slugs": ["doc-1", "doc-2"],
  "pillars": [
    {
      "title": "Impacto ambiental",
      "context_instructions": "...",
      "metrics": [
        {
          "title": "Emisiones totales",
          "instructions": "...",
          "response_type": "qualitative"
        },
        {
          "title": "Calificación",
          "instructions": "...",
          "response_type": "quantitative",
          "scale_min": 0,
          "scale_max": 5
        }
      ]
    }
  ]
}
```

### 6.3 Ejecutar Evaluación

```
POST /api/evaluations/<slug>/runs/
Body: {
  "project_slug": "proyecto-demo",
  "document_slugs": ["doc-3"],
  "model": "gpt-4o-mini",
  "temperature": 0.1,
  "language": "es",
  "instructions_override": "..."
}
```

**Respuesta 201 (inmediata):**
```json
{
  "id": 17,
  "status": "pending",
  "document_snapshot": [{"slug": "doc-1", "name": "Reporte 2024"}],
  "pillar_results": []
}
```

### 6.4 Consultar Run

```
GET /api/evaluations/<slug>/runs/<run_id>/
```

Cuando `status` es `completed`:
```json
{
  "id": 17,
  "status": "completed",
  "error_message": "",
  "pillar_results": [
    {
      "pillar": 3,
      "summary": "...",
      "metric_results": [
        {
          "metric": 8,
          "response_type": "quantitative",
          "response_text": "...",
          "response_value": 4.0,
          "chunk_ids": [42, 43],
          "sources": [{"document_slug": "doc-1", "chunk_index": 10}]
        }
      ]
    }
  ]
}
```

**Estados de run:** `pending`, `running`, `completed`, `failed`.

---

## 7. Módulo Plantillas de Evaluación

**Base:** `/api/evaluation-templates/` y `/api/evaluations/run/`, `/api/evaluations/runs/`

### 7.1 Endpoints

| Método | Path | Descripción |
|--------|------|-------------|
| GET | `/api/evaluation-templates/` | Listar plantillas (ASG Allen Manza, etc.) |
| POST | `/api/evaluations/run/` | Ejecutar evaluación ASG sobre proyecto |
| GET | `/api/evaluations/runs/` | Listar ejecuciones con filtros |
| GET | `/api/evaluations/runs/?runId=<uuid>` | Detalle de un run |

### 7.2 Listar Plantillas

```
GET /api/evaluation-templates/
```

**Respuesta:**
```json
[
  {
    "id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
    "name": "ASG Allen Manza",
    "description": "...",
    "methodology": "ASG Allen Manza",
    "pillars": [
      {
        "id": "...",
        "code": "A",
        "name": "Ambiental",
        "weight": "0.33",
        "kpis": [
          {"id": "...", "code": "A1", "name": "Cambio climático", "max_score": 3}
        ]
      }
    ]
  }
]
```

### 7.3 Ejecutar Evaluación ASG

```
POST /api/evaluations/run/
Body: {
  "projectId": 1,
  "templateId": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d"
}
```

Acepta `camelCase` o `snake_case`.

### 7.4 Listar Runs con Filtros

```
GET /api/evaluations/runs/?projectId=1&templateId=<uuid>&runId=<uuid>
```

---

## 8. Modelos de Datos y Tipos

### 8.1 Resumen de Entidades

| Entidad | Identificador | Relaciones clave |
|---------|---------------|------------------|
| User | `id` | - |
| Document | `slug` | owner (User) |
| SmartChunk | `id` | document |
| ChatSession | `id` | owner, allowed_documents |
| ChatMessage | `id` | session |
| Project | `slug` | owner, documents (M2M) |
| Evaluation | `slug` | owner, pillars, documents |
| EvaluationRun | `id` | evaluation |

### 8.2 Permisos por Módulo

| Módulo | Usuario regular | Staff |
|--------|-----------------|-------|
| Documentos | Propios + públicos + compartidos | Todos |
| Chat | Propias sesiones | Todas |
| Proyectos | Propios + compartidos | Todos |
| Evaluaciones | Propias + compartidas + públicas | Todas |

### 8.3 Compartición

- **DocumentShare**, **ProjectShare**, **EvaluationShare**: `user_id` + `role` (`viewer` | `editor`).
- Documentos en proyectos compartidos son accesibles según el rol del proyecto.

---

## 9. Flujos de Integración

### 9.1 Flujo: Usuario sube documento y chatea

```
1. POST /api/auth/login/ → access, refresh, user
2. POST /api/document/create/ (multipart) → documento creado
3. [Opcional] GET /api/document/<slug>/ → ver chunking_status hasta "done"
4. POST /api/chat/sessions/ { document_slugs: [slug] }
5. POST /api/chat/messages/ { session: id, content: "..." }
6. Mostrar assistant_message.content y assistant_message.chunks (fuentes)
```

### 9.2 Flujo: Evaluación sobre proyecto

```
1. POST /api/projects/ → crear proyecto
2. POST /api/projects/<slug>/documents/ { document_slugs: [...] }
3. POST /api/evaluations/run/ { projectId, templateId }
   o POST /api/evaluations/<slug>/runs/ para evaluaciones custom
4. GET /api/evaluations/runs/?projectId=X o GET /api/evaluations/<slug>/runs/<run_id>/
5. Polling hasta status === "completed" o "failed"
```

### 9.3 Flujo: Refresh de token en 401

```
1. Request devuelve 401 con code "token_not_valid"
2. POST /api/auth/token/refresh/ { refresh: <cookie o storage> }
3. Si 200: actualizar access (y refresh si viene en respuesta)
4. Reintentar request original
5. Si 401 en refresh: redirigir a login
```

---

## 10. Configuración Frontend

### 10.1 Variables de Entorno

```bash
NEXT_PUBLIC_API_URL=https://api.ecofilia.site
NEXT_PUBLIC_BACKEND_URL=https://api.ecofilia.site
AUTH_COOKIE_DOMAIN=.ecofilia.site
AUTH_COOKIE_NAME=ecofilia_refresh
AUTH_COOKIE_MAX_AGE=604800
```

**Una sola URL base** para todos los módulos. No se necesitan variables separadas por módulo.

### 10.2 Cliente API Recomendado

- Usar un cliente centralizado que:
  - Añada `Authorization: Bearer <access>` a todas las peticiones protegidas
  - Intercepte 401 y ejecute refresh automático
  - Actualice la cookie de refresh cuando el backend rote el token
  - Use `credentials: 'include'` para cookies en requests al mismo dominio

### 10.3 CORS

- Backend espera `Origin` en la lista `CORS_ALLOWED_ORIGINS`.
- En desarrollo: `http://localhost:3000`, `http://127.0.0.1:3000`.
- Credentials: permitidos para cookies.

### 10.4 Rate Limits (por defecto)

- Anónimos: 30/min
- Autenticados: 120/min
- Refresh token: 20/min (scope `strict_refresh`)

---

## 11. Checklist de Integrabilidad

### Autenticación
- [ ] Login con email/password (y OTP si MFA)
- [ ] Guardar refresh en cookie HTTP-only o storage seguro
- [ ] Enviar `Authorization: Bearer <access>` en todas las peticiones protegidas
- [ ] Implementar refresh automático en 401
- [ ] Actualizar cookie con nuevo refresh tras rotación
- [ ] Logout invalida refresh en backend

### Documentos
- [ ] Subida con `multipart/form-data` (campo `file`)
- [ ] Listado con filtros opcionales
- [ ] RAG query con `query` y filtros `documents`, `public`
- [ ] Manejar `chunking_status` para feedback de procesamiento

### Chat
- [ ] Crear sesión con `document_slugs` (puede ser vacío)
- [ ] Enviar mensajes a `POST /api/chat/messages/`
- [ ] Mostrar `assistant_message.content` y `chunks` como fuentes

### Proyectos
- [ ] CRUD de proyectos
- [ ] Añadir/quitar documentos
- [ ] Compartir con `user_id` y `role`

### Evaluaciones
- [ ] Crear evaluaciones custom con pilares/métricas
- [ ] Ejecutar runs y consultar estado
- [ ] Plantillas: `GET /api/evaluation-templates/`, `POST /api/evaluations/run/`
- [ ] Polling de runs hasta `completed` o `failed`

### General
- [ ] Manejo de errores 400, 401, 403, 404, 429, 500
- [ ] Content-Type correcto (JSON o multipart según endpoint)
- [ ] URLs relativas desde `NEXT_PUBLIC_API_URL`

---

## Referencias

- **API completa:** `backend/API_DOCUMENTATION.md`
- **Guía de auth Next.js:** `FRONTEND_AUTH_IMPLEMENTATION_GUIDE.md`
- **Documentación técnica:** `backend/TECHNICAL_DOCUMENTATION.md`
- **Evaluación dashboards:** `backend/EVALUATION_DASHBOARDS_API.md`
