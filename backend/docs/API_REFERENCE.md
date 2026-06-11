# Ecofilia Backend — API Reference

Documentación completa del backend Django para consumo desde el frontend.

- **Base URL (prod):** `https://api.ecofilia.site`
- **Base URL (local):** `http://localhost:8000`
- **Autenticación:** Bearer JWT en todos los endpoints salvo los marcados como `Public`
- **Contenido:** `application/json` (salvo upload de archivos → `multipart/form-data`)
- **Paginación:** cuando el endpoint pagina, devuelve `{ count, next, previous, results }`

> **Nota sobre el motor RAG (PR #2 — rama `claude/nice-allen-yn8wph`):**
> las capacidades de recuperación y generación se ampliaron sustancialmente.
> Esta documentación refleja el estado post-merge. Los campos nuevos en
> `metadata` de mensajes de chat están marcados con `[F1-F5]`.

---

## Índice

1. [Autenticación](#1-autenticación)
2. [Documentos](#2-documentos)
3. [Chat](#3-chat)
4. [Proyectos](#4-proyectos)
5. [Skills](#5-skills)
6. [Evaluaciones](#6-evaluaciones)
7. [Health Check](#7-health-check)
8. [Motor RAG — campos de diagnóstico](#8-motor-rag--campos-de-diagnóstico)
9. [SSE — protocolo de streaming](#9-sse--protocolo-de-streaming)
10. [Códigos de error comunes](#10-códigos-de-error-comunes)

---

## 1. Autenticación

Base path: `/api/auth/`

### 1.1 Registro

`POST /api/auth/register/` — `Public`

```json
// Request
{
  "email": "user@example.com",
  "password": "min8chars",
  "first_name": "Ana",         // opcional
  "last_name": "García"        // opcional
}

// Response 201
{
  "user": {
    "id": 1,
    "email": "user@example.com",
    "first_name": "Ana",
    "last_name": "García",
    "role": "viewer",
    "is_superuser": false,
    "email_verified": false,
    "approved": false,
    "mfa_enabled": false
  },
  "detail": "Cuenta creada. Revisá tu email para verificar."
}
```

---

### 1.2 Login

`POST /api/auth/login/` — `Public`

```json
// Request
{
  "email": "user@example.com",
  "password": "password123",
  "otp": "123456"   // requerido solo si mfa_enabled=true
}

// Response 200
{
  "access": "<jwt>",
  "refresh": "<jwt>",
  "user": { /* ProfileSerializer — ver 1.1 */ }
}

// Response 401 — credenciales incorrectas
{ "detail": "No active account found with the given credentials" }
```

---

### 1.3 Refresh token

`POST /api/auth/token/refresh/` — `Public`

```json
// Request
{ "refresh": "<jwt>" }

// Response 200
{ "access": "<jwt>", "refresh": "<jwt>" }

// Response 401 — token expirado o inválido
{ "detail": "Token is invalid or expired", "code": "token_not_valid" }
```

---

### 1.4 Logout

`POST /api/auth/logout/` — `Auth`

```json
// Request
{ "refresh": "<jwt>" }

// Response 204 (no body)
```

---

### 1.5 Verificación de email

`POST /api/auth/verify-email/` — `Public`

```json
// Request
{ "uid": "...", "token": "..." }

// Response 200
{ "detail": "Email verificado correctamente." }
```

---

### 1.6 Reseteo de contraseña

`POST /api/auth/password/reset/` — `Public`

```json
// Request
{ "email": "user@example.com" }
// Response 200 — siempre 200 (no revela si el email existe)
{ "detail": "..." }
```

`POST /api/auth/password/reset/confirm/` — `Public`

```json
// Request
{ "uid": "...", "token": "...", "new_password": "nuevapass123" }
// Response 200
{ "detail": "Contraseña actualizada." }
```

---

### 1.7 Cambio de contraseña

`POST /api/auth/password/change/` — `Auth`

```json
// Request
{ "old_password": "...", "new_password": "..." }
// Response 200
{ "detail": "Contraseña actualizada." }
```

---

### 1.8 Perfil del usuario

`GET /api/auth/me/` — `Auth`

```json
// Response 200
{
  "id": 1,
  "email": "user@example.com",
  "first_name": "Ana",
  "last_name": "García",
  "role": "viewer",       // viewer | editor | admin | superadmin
  "is_superuser": false,
  "email_verified": true,
  "approved": true,
  "mfa_enabled": false
}
```

`PATCH /api/auth/me/` — `Auth`

```json
// Request (todos opcionales)
{ "first_name": "Ana", "last_name": "García" }
// Response 200 — ProfileSerializer
```

---

### 1.9 MFA (autenticación de dos factores)

`POST /api/auth/mfa/setup/` — `Auth`

```json
// Response 201
{ "secret": "BASE32SECRET", "otpauth_url": "otpauth://totp/..." }
```

`POST /api/auth/mfa/verify/` — `Auth`

```json
// Request
{ "code": "123456" }
// Response 200
{ "detail": "MFA habilitado." }
```

`POST /api/auth/mfa/disable/` — `Auth`

```json
// Request
{ "code": "123456" }
// Response 200
{ "detail": "MFA deshabilitado." }
```

---

## 2. Documentos

Base path: `/api/document/`

### Objeto Document

```json
{
  "id": 42,
  "slug": "ndc-argentina-2023",
  "name": "NDC Argentina 2023",
  "category": "Clima",
  "category_slug": "clima",
  "category_path": ["biblioteca", "clima"],
  "description": "Contribución Determinada a Nivel Nacional...",
  "content_summary": "Resumen auto-generado...",
  "file": "https://...",
  "is_public": false,
  "is_owner": true,
  "owner_email": "user@example.com",
  "created_at": "2024-01-15T10:30:00Z",
  "chunking_status": "done",   // pending | processing | done | error
  "chunking_done": true,
  "last_error": null
}
```

---

### 2.1 Upload de documento

`POST /api/document/create/` — `Auth` — `multipart/form-data`

| Campo | Tipo | Requerido |
|---|---|---|
| `file` | File | ✅ |
| `name` | string | — |
| `category_slug` | slug | — |
| `description` | string | — |
| `is_public` | boolean | — (solo admin) |
| `project_slug` | slug | — |

```json
// Response 201 — DocumentSerializer (ver arriba)
```

---

### 2.2 Upload masivo

`POST /api/document/create/bulk/` — `Auth` — `multipart/form-data`

| Campo | Tipo | Notas |
|---|---|---|
| `files` | File[] | 1–100 archivos |
| `category_slug` | slug | se aplica a todos |
| `project_slug` | slug | opcional |

```json
// Response 201/207
{
  "created": 3,
  "successful": [
    { "filename": "ndc-ar.pdf", "id": 42, "slug": "ndc-ar" }
  ],
  "failed": [
    { "filename": "corrupto.pdf", "error": "File is empty" }
  ],
  "documents": [ /* DocumentSerializer[] */ ]
}
```

---

### 2.3 Listar documentos

`GET /api/document/list/` — `Auth`

| Query param | Valores | Default |
|---|---|---|
| `scope` | `own` \| `public` \| `shared` \| `all` | `all` |
| `paginate` | `1` | — |
| `page` / `page_size` | integer | — |
| `library_category` | slug | — |
| `library_category_subtree` | `1` | — |
| `summary` | `category_tree` \| `categories` | — |
| `sort` | `recent` \| `oldest` \| `title` \| `title-desc` | `recent` |
| `ids` | CSV de integers (máx 200) | — |

```json
// Response 200 — array sin paginar
[ /* DocumentSerializer[] */ ]

// Response 200 — paginado
{ "count": 150, "next": "...", "previous": null, "results": [ /* ... */ ] }

// Response 200 — summary=category_tree
{
  "uncategorized_count": 5,
  "tree": [
    { "slug": "clima", "name": "Clima", "document_count": 12, "children": [] }
  ]
}
```

---

### 2.4 Detalle, edición, borrado

`GET /api/document/{slug}/` → `DocumentDetailSerializer` (incluye `content_summary`)

`PATCH /api/document/{slug}/` — campos: `name`, `category_slug`, `description`, `is_public` (admin)

`DELETE /api/document/{slug}/` — `204`

---

### 2.5 Chunk por índice (para expandir una cita)

`GET /api/document/{slug}/chunks/{chunk_index}/` — `Auth`

```json
// Response 200
{
  "id": 1234,
  "content": "El texto del fragmento...",
  "chunk_index": 7,
  "document_id": 42,
  "document_slug": "ndc-argentina-2023",
  "document_name": "NDC Argentina 2023",
  "document_file": "https://...",
  "title": "Sección 3 — Mitigación",
  "summary": "Resumen del fragmento...",
  "context_summary": "Contexto generado por LLM...",
  "token_count": 420,
  "page_number": 14,
  "created_at": "2024-01-15T10:35:00Z"
}
```

> **Uso típico:** cuando el usuario hace clic en `[#N]` en una respuesta de chat, el frontend usa `chunk_ids` del mensaje para obtener el fragmento de origen y mostrarlo en un panel lateral.

---

### 2.6 Búsqueda RAG (librería)

`GET /api/document/rag/` — `Auth`

| Query param | Tipo | Notas |
|---|---|---|
| `query` | string | requerido |
| `documents` | CSV de slugs | opcional |
| `public` | boolean | opcional |

```json
// Response 200
{
  "query": "altura máxima edificación zona R1",
  "results": [
    {
      "id": 1234,
      "content": "...",
      "chunk_index": 7,
      "document_id": 42,
      "token_count": 420,
      "created_at": "..."
    }
  ]
}
```

---

### 2.7 Compartir documentos

`GET /api/document/{slug}/shares/` — lista compartidos

`POST /api/document/{slug}/shares/`
```json
{ "user_email": "otro@example.com", "role": "viewer" }  // role: viewer | editor
```

`PATCH /api/document/{slug}/shares/{share_id}/`
```json
{ "role": "editor" }
```

`DELETE /api/document/{slug}/shares/{share_id}/` — `204`

---

### 2.8 Sesión de chat de documento

`GET /api/document/{slug}/chat-session/` → `ChatSessionSerializer`

`POST /api/document/{slug}/chat-session/` — crea o recupera la sesión default

---

### 2.9 Categorías

`GET /api/document/categories/` — lista árbol

`POST /api/document/categories/`
```json
{ "name": "Biodiversidad", "parent_slug": "medio-ambiente" }
```

`PATCH /api/document/categories/{slug}/` | `DELETE /api/document/categories/{slug}/`

---

## 3. Chat

Base path: `/api/chat/`

### Objeto ChatSession

```json
{
  "id": 10,
  "session_type": "document",  // document | project | library | copilot
  "title": "Análisis NDC Argentina",
  "system_prompt": null,
  "model": "gpt-4o-mini",      // o "claude-sonnet-4-6" con LLM_PROVIDER=anthropic
  "temperature": 0.1,
  "language": "es",
  "is_active": true,
  "created_at": "2024-01-15T10:00:00Z",
  "updated_at": "2024-01-15T11:30:00Z",
  "document_slugs": ["ndc-argentina-2023"],
  "primary_document_slug": "ndc-argentina-2023",
  "project_slug": null
}
```

---

### Objeto ChatMessage

```json
{
  "id": 55,
  "session": 10,
  "role": "assistant",   // user | assistant | system
  "content": "La meta de mitigación de Argentina es no superar 349 MtCO2e en 2030 [#1].",
  "chunk_ids": [1234, 1235],
  "chunks": [
    {
      "id": 1234,
      "chunk_index": 7,
      "document_slug": "ndc-argentina-2023",
      "document_name": "NDC Argentina 2023"
    }
  ],
  "metadata": {
    "usage": { "input_tokens": 1200, "output_tokens": 85, "total_tokens": 1285 },

    // ── Diagnósticos del motor RAG [F1-F5] ──────────────────────────────────
    "rag_diagnostics": {
      "query_type": "numeric",
      "coverage_mode": "focused",
      "vector_candidates": 20,
      "lexical_candidates": 8,
      "fused_candidates": 15,
      "final_chunks": 4,
      "unique_documents": 1,
      "max_similarity": 0.82,
      "avg_similarity": 0.71,
      "retrieval_confidence": "high",   // high | medium | low | none
      "below_threshold_kept": 0,        // [F1] chunks que antes se descartaban
      "parent_expansion": {             // [F1] small-to-big
        "anchors": 4,
        "expanded": 8,
        "window": 1
      },
      "adaptive_budget": 12,            // [F1] si se aplicó budget adaptativo
      "retrieval_plan": {               // [F3] plan del router de tareas
        "strategy": "global",           // global | hybrid_per_document
        "coverage_mode": "focused",
        "per_doc": 1,
        "expand": true,
        "model_role": "balanced",       // fast | balanced | deep
        "per_document_answer": false
      },
      "fanout": false,                  // [F4] true si se usó map-reduce
      "fanout_documents": 0,            // [F4]
      "fanout_documents_found": 0,      // [F4]
      "elapsed_seconds": 0.45
    },

    // ── Análisis de la query ─────────────────────────────────────────────────
    "query_analysis": {
      "query_type": "numeric",           // factual|numeric|extract_per_entity|comparative|panorama
      "coverage_mode": "focused",        // focused | balanced | all
      "locality": "localized",           // localized | distributed  [F3]
      "operation": "extract",            // lookup|extract|compare|synthesize  [F3]
      "is_general": false,
      "keywords": ["meta", "mitigacion"],
      "sub_queries": []
    },

    // ── Citas [#N] → chunks ──────────────────────────────────────────────────
    "citations": [
      {
        "index": 1,
        "chunk_id": 1234,
        "chunk_index": 7,
        "document_slug": "ndc-argentina-2023",
        "document_name": "NDC Argentina 2023",
        "page_number": 14
      }
    ],
    "retrieval_chunk_ids": [1234, 1235],
    "citation_integrity": "ok",  // ok | partial | none

    "response_mode": null          // si se sobreescribió el modo de respuesta
  },
  "created_at": "2024-01-15T11:30:00Z"
}
```

---

### 3.1 Sesiones

`GET /api/chat/sessions/` — `Auth`

| Query param | Tipo | Notas |
|---|---|---|
| `page` / `page_size` | integer | paginado |
| `include_empty` | `1` | incluye sesiones sin mensajes |

`POST /api/chat/sessions/` — crea sesión

```json
// Request
{
  "title": "Análisis NDC Argentina",
  "document_slugs": ["ndc-argentina-2023"],  // hasta 20 slugs
  "model": "gpt-4o-mini",     // opcional — default según LLM_PROVIDER
  "temperature": 0.1,
  "language": "es",
  "system_prompt": null
}
// Response 201 — ChatSessionSerializer
```

`GET /api/chat/sessions/{id}/` → `ChatSessionSerializer`

`DELETE /api/chat/sessions/{id}/` → `204`

---

### 3.2 Mensajes (no-streaming)

`GET /api/chat/messages/?session={id}` → array de `ChatMessageSerializer`

`POST /api/chat/messages/` — `Auth`

```json
// Request
{
  "session": 10,
  "content": "¿Cuál es la meta de mitigación de Argentina?",
  "document_slugs": ["ndc-argentina-2023"],  // opcional — actualiza el scope
  "response_mode": "puntual"                 // ver tabla abajo
}

// Response 201
{
  "user_message": { /* ChatMessageSerializer */ },
  "assistant_message": { /* ChatMessageSerializer con metadata completo */ }
}
```

**Valores de `response_mode`:**

| Valor | Qué hace |
|---|---|
| `puntual` | Respuesta breve y concisa (factual/numérica) |
| `panorama` | Síntesis extensa de toda la base documental |
| `comparacion` | Análisis comparativo entre documentos |
| `extraccion` | Extracción de datos específicos (activa fan-out per-entity) |
| `tabla` | Salida estructurada en tabla |
| `null` / omitido | El router decide automáticamente según la consulta [F3] |

---

### 3.3 Streaming (SSE)

`POST /api/chat/messages/stream/` — `Auth`

Request igual a `POST /api/chat/messages/`. Response: stream `text/event-stream`.

Ver sección [9. SSE — protocolo de streaming](#9-sse--protocolo-de-streaming).

---

## 4. Proyectos

Base path: `/api/projects/`

### Objeto Project

```json
{
  "id": 5,
  "slug": "proyecto-esg-minera",
  "name": "Proyecto ESG Minera",
  "description": "...",
  "is_active": true,
  "owner": 1,
  "owner_email": "user@example.com",
  "documents": [
    {
      "id": 42, "slug": "ndc-ar", "name": "NDC Argentina",
      "category": "Clima", "is_primary": true, "note": "", "created_at": "..."
    }
  ],
  "enabled_skill_slugs": ["analisis-esg"],
  "blueprint_document_slug": null,
  "context_notes": {},
  "copilot_enabled": true,
  "structure_template_slug": null,
  "can_edit": true,
  "can_manage_shares": true,
  "created_at": "...",
  "updated_at": "..."
}
```

---

### 4.1 CRUD proyectos

`GET /api/projects/` → lista `ProjectSerializer[]`

`POST /api/projects/`
```json
{
  "name": "Proyecto ESG Minera",
  "description": "...",
  "document_slugs": ["ndc-ar", "informe-ambiental"],
  "enabled_skill_slugs": ["analisis-esg"],
  "copilot_enabled": true
}
```

`GET /api/projects/{slug}/` | `PATCH /api/projects/{slug}/` | `DELETE /api/projects/{slug}/`

---

### 4.2 Documentos del proyecto

`POST /api/projects/{slug}/documents/`
```json
{ "document_slugs": ["nuevo-doc"] }
```

`DELETE /api/projects/{slug}/documents/{document_slug}/` → `204`

---

### 4.3 Compartir proyectos

`GET /api/projects/{slug}/shares/` | `POST` | `PATCH /{share_id}/` | `DELETE /{share_id}/`

```json
// POST Request
{ "user_email": "colaborador@example.com", "role": "editor" }  // viewer | editor | admin
```

---

### 4.4 Chat del proyecto

`GET /api/projects/{slug}/chat-sessions/` → lista de sesiones

`POST /api/projects/{slug}/chat-sessions/`
```json
{
  "title": "Consultas NDC",
  "document_slugs": ["ndc-ar"],
  "model": "claude-sonnet-4-6"
}
```

---

### 4.5 Estructura de entregables

`GET /api/projects/{slug}/deliverables/` → lista de entregables

`POST /api/projects/{slug}/deliverables/`
```json
{ "name": "Informe ESG 2024", "template_slug": "informe-esg-estandar" }
```

### Objeto ProjectDeliverable

```json
{
  "id": 3,
  "name": "Informe ESG 2024",
  "slug": "informe-esg-2024",
  "template_slug": "informe-esg-estandar",
  "is_primary": true,
  "position": 1,
  "status": "draft",   // draft | in_progress | review | done
  "sections_count": 8,
  "completed_sections": 3,
  "created_at": "...",
  "updated_at": "..."
}
```

`GET /api/projects/{slug}/deliverables/{deliv_slug}/structure/`

```json
{
  "deliverable_slug": "informe-esg-2024",
  "deliverable_name": "Informe ESG 2024",
  "template_slug": "informe-esg-estandar",
  "sections": [ /* ProjectSectionSerializer[] */ ]
}
```

`PUT /api/projects/{slug}/deliverables/{deliv_slug}/structure/initialize/`
```json
{ "template_slug": "informe-esg-estandar" }
```

### Objeto ProjectSection

```json
{
  "id": 20,
  "title": "3. Gestión del agua",
  "description": "Análisis de consumo hídrico...",
  "position": 3,
  "status": "in_progress",   // draft | in_progress | review | done
  "notes": "Revisar datos de 2023",
  "output_snapshot": "El consumo hídrico...",
  "suggested_skill_slugs": ["analisis-agua"],
  "deliverable_slug": "informe-esg-2024",
  "updated_at": "...",
  "created_at": "..."
}
```

`POST /api/projects/{slug}/deliverables/{deliv_slug}/sections/`
```json
{ "title": "3. Gestión del agua", "description": "...", "position": 3 }
```

`PATCH /api/projects/{slug}/deliverables/{deliv_slug}/sections/{position}/`
```json
{ "status": "done", "output_snapshot": "Texto aprobado..." }
```

---

### 4.6 Copilot del proyecto

`GET /api/projects/{slug}/copilot/sessions/` → lista sesiones

`POST /api/projects/{slug}/copilot/sessions/`
```json
{ "deliverable_slug": "informe-esg-2024" }
```

`POST /api/projects/{slug}/copilot/messages/`
```json
{
  "content": "Redactá la sección de agua basándote en los documentos",
  "session": 10   // opcional — si se omite usa la sesión default
}
```

`POST /api/projects/{slug}/copilot/autocomplete/`
```json
{
  "before": "El consumo hídrico de la operación en 2023 fue de ",
  "after": " metros cúbicos, representando...",
  "section_position": 3,
  "doc_title": "Informe Ambiental 2023"
}
// Response 200
{ "completion": "4.500", "usage": { "input_tokens": 300, "output_tokens": 5 } }
```

---

### 4.7 Plantillas de estructura

`GET /api/projects/structure-templates/` → lista

`POST /api/projects/structure-templates/`
```json
{
  "name": "Informe ESG Estándar",
  "sections": [
    { "title": "1. Gobernanza", "description": "...", "position": 1 },
    { "title": "2. Medio Ambiente", "description": "...", "position": 2 }
  ]
}
```

`GET /api/projects/structure-templates/{slug}/` | `PATCH` | `DELETE`

---

## 5. Skills

Base path: `/api/skills/`

### Objeto Skill

```json
{
  "id": 8,
  "slug": "analisis-esg-rapido",
  "name": "Análisis ESG Rápido",
  "description": "Extrae indicadores ESG clave del documento.",
  "skill_type": "quick",             // quick | copilot
  "allowed_contexts": ["document", "project"],
  "system_prompt": "Sos un analista ESG...",
  "prompt_template": "Analizá los siguientes fragmentos:\n{{context_block}}\n\n{{extra_instructions}}",
  "model": "gpt-4o-mini",
  "temperature": 0.1,
  "comparative_mode_enabled": false,
  "strict_missing_evidence": true,
  "retrieval_strategy": "global",    // global | hybrid_per_document | auto
  "k_per_doc": 2,
  "total_limit": 8,
  "max_per_doc_after_rerank": 3,
  "default_output_mode": "text",     // text | table
  "pinned_document_slugs": [],
  "tools_enabled": false,
  "research_phase_enabled": false,
  "steps": [],                       // solo copilot — SkillStepSerializer[]
  "parameters": [],
  "is_template": false,
  "is_default_enabled": false,
  "owner_email": "user@example.com",
  "created_at": "...",
  "updated_at": "..."
}
```

---

### 5.1 CRUD skills

`GET /api/skills/` | `POST /api/skills/`

| Query param | Tipo | Notas |
|---|---|---|
| `skill_type` | `quick` \| `copilot` | filtra por tipo |
| `context` | `document` \| `project` \| `repository` \| `any` | filtra por contexto |
| `context_slug` | slug | skills disponibles para ese contexto específico |

`GET /api/skills/{slug}/` | `PATCH /api/skills/{slug}/` | `DELETE /api/skills/{slug}/`

---

### 5.2 Ejecutar un skill

`POST /api/skills/{slug}/run/` — `Auth`

```json
// Request
{
  "context_type": "document",        // document | project | repository
  "context_slug": "ndc-argentina-2023",
  "extra_instructions": "Enfocate en las metas de mitigación",
  "input_values": { "año": "2030" }, // valores de parámetros del skill
  "document_slugs": ["ndc-ar"],      // opcional — override del scope
  "output_mode": "text",             // text | table
  "table_columns": ["País", "Meta", "Año"],  // solo mode=table
  // Opciones específicas de copilot:
  "step_document_overrides": { "1": ["doc-a"], "2": ["doc-b"] },
  "review_each_step": false          // true = pausar en cada paso para aprobación
}

// Response 200 (quick) / 202 (copilot en background)
// → SkillExecutionSerializer
```

### Objeto SkillExecution

```json
{
  "id": 99,
  "skill": 8,
  "skill_name": "Análisis ESG Rápido",
  "skill_type": "quick",
  "status": "done",   // pending | running | done | failed | awaiting_approval
  "context_label": "NDC Argentina 2023",
  "project_slug": null,
  "document_slug": "ndc-argentina-2023",
  "extra_instructions": "...",
  "input_values": {},
  "output_mode": "text",
  "output": "El documento establece que...",
  "output_structured": {},          // relleno cuando output_mode=table
  "edited_output": null,            // si el usuario editó el output
  "edited_at": null,
  "steps_completed": 0,
  "steps_total": 0,
  "current_step_position": null,
  "metadata": {
    "usage": { "input_tokens": 800, "output_tokens": 200, "total_tokens": 1000 },
    "chunks_used": 6,
    "retrieval_strategy_used": "global",
    "sources": [
      { "document_slug": "ndc-ar", "document_name": "NDC Argentina", "chunk_index": 7 }
    ]
  },
  "error_message": null,
  "started_at": "...",
  "finished_at": "...",
  "created_at": "..."
}
```

---

### 5.3 Executions — listado y detalle

`GET /api/skills/executions/` — filtros: `skill`, `project`, `status`

`GET /api/skills/executions/{id}/`

`DELETE /api/skills/executions/{id}/`

---

### 5.4 Copilot — aprobación y re-generación

`POST /api/skills/executions/{id}/approve/`
```json
// Request
{ "override_content": "Texto editado antes de continuar..." }  // opcional
// Response 202 — SkillExecutionSerializer (status=running o siguiente paso)
```

`POST /api/skills/executions/{id}/regenerate-step/` → `202`

---

### 5.5 Versiones de output

`GET /api/skills/executions/{id}/versions/`

```json
// Response 200
[
  {
    "id": 5,
    "version_number": 2,
    "label": "Versión revisada",
    "content": "...",
    "created_by_email": "user@example.com",
    "created_at": "..."
  }
]
```

`POST /api/skills/executions/{id}/versions/`
```json
{ "content": "Texto editado final", "label": "v2 aprobada" }
// Response 201 → { "version": VersionSerializer, "execution": ExecutionSerializer }
```

`POST /api/skills/executions/{id}/versions/{version_number}/restore/` → `200`

`POST /api/skills/executions/{id}/reset-edit/` → `200` — descarta edición manual

---

## 6. Evaluaciones

Base path: `/api/evaluations/`

### Objeto Evaluation

```json
{
  "id": 3,
  "slug": "eval-esg-2024",
  "title": "Evaluación ESG 2024",
  "description": "...",
  "visibility": "private",   // private | shared | public
  "system_prompt": "...",
  "language": "es",
  "model": "gpt-4o-mini",
  "temperature": 0.1,
  "is_active": true,
  "project_slug": "proyecto-esg",
  "owner_email": "user@example.com",
  "documents": [
    { "id": 42, "slug": "ndc-ar", "name": "NDC Argentina", "note": "" }
  ],
  "pillars": [
    {
      "id": 10,
      "name": "Cambio Climático",
      "metrics": [
        { "id": 20, "name": "Reducción de emisiones", "weight": 0.4,
          "response_type": "qualitative" }
      ]
    }
  ],
  "can_edit": true,
  "can_manage_shares": true,
  "created_at": "...",
  "updated_at": "..."
}
```

---

### 6.1 CRUD evaluaciones

`GET /api/evaluations/` | `POST /api/evaluations/`

`GET /api/evaluations/{slug}/` | `PATCH /api/evaluations/{slug}/` | `DELETE /api/evaluations/{slug}/`

---

### 6.2 Ejecutar evaluación

`POST /api/evaluations/run/` — `Auth`

```json
// Request
{
  "evaluation_slug": "eval-esg-2024",
  "project_slug": "proyecto-esg",    // opcional
  "document_slugs": ["ndc-ar"]       // opcional — override del scope
}
// Response 202 — EvaluationRunSerializer
```

### Objeto EvaluationRun

```json
{
  "id": 7,
  "evaluation": 3,
  "evaluation_slug": "eval-esg-2024",
  "project_slug": "proyecto-esg",
  "owner": 1,
  "status": "running",   // pending | running | done | failed
  "model": "gpt-4o-mini",
  "temperature": 0.1,
  "results": [
    {
      "pillar": "Cambio Climático",
      "metric": "Reducción de emisiones",
      "score": 0.78,
      "justification": "...",
      "evidence_quality": {
        "chunks_retrieved": 6,
        "chunks_above_threshold": 5,
        "avg_similarity": 0.74,
        "evidence_level": "high"
      }
    }
  ],
  "created_at": "...",
  "finished_at": "..."
}
```

---

### 6.3 Runs — listado y detalle

`GET /api/evaluations/runs/` → lista

`GET /api/evaluations/runs/{id}/`

`DELETE /api/evaluations/runs/{id}/`

---

### 6.4 Compartir evaluaciones

`GET /api/evaluations/{slug}/shares/` | `POST` | `PATCH /{share_id}/` | `DELETE /{share_id}/`

```json
// POST Request
{ "user_email": "colaborador@example.com", "role": "viewer" }
```

---

### 6.5 Plantillas de evaluación

`GET /api/evaluation-templates/` | `POST /api/evaluation-templates/`

`GET /api/evaluation-templates/{slug}/` | `PATCH` | `DELETE`

---

## 7. Health Check

`GET /health/` — `Public`

```json
// Response 200
{ "status": "ok" }
```

---

## 8. Motor RAG — campos de diagnóstico

Desde el PR #2 (F1–F5), el objeto `metadata.rag_diagnostics` de los mensajes
de chat contiene información rica para debug, trazabilidad y observabilidad.

### 8.1 Campos clave

| Campo | Tipo | Descripción |
|---|---|---|
| `query_type` | string | Tipo detectado: `factual` \| `numeric` \| `extract_per_entity` \| `comparative` \| `panorama` |
| `coverage_mode` | string | `focused` \| `balanced` \| `all` |
| `retrieval_confidence` | string | `high` (>0.78) \| `medium` (>0.55) \| `low` \| `none` |
| `final_chunks` | int | Fragmentos que llegaron al LLM |
| `unique_documents` | int | Documentos distintos representados |
| `below_threshold_kept` | int | [F1] Fragmentos que habrían sido descartados con el umbral duro |
| `parent_expansion` | object | [F1] Si se aplicó small-to-big: `anchors`, `expanded`, `window` |
| `adaptive_budget` | int | [F1] Budget dinámico calculado (tareas multi-doc) |
| `retrieval_plan` | object | [F3] Plan del router: `strategy`, `coverage_mode`, `model_role`, `per_document_answer` |
| `fanout` | bool | [F4] Si se ejecutó el map-reduce por documento |
| `fanout_documents` | int | [F4] Documentos procesados en el fan-out |
| `fanout_documents_found` | int | [F4] Documentos donde se encontró el dato |
| `elapsed_seconds` | float | Tiempo total de retrieval |

### 8.2 Tipos de query y qué esperar

| `query_type` | Ejemplo | Motor activa |
|---|---|---|
| `factual` | "¿Qué es una NDC?" | Retrieval global + 1 chunk |
| `numeric` | "¿Cuál es la altura máxima en zona R1?" | Lexical boost + small-to-big |
| `extract_per_entity` | "Extraé la meta de cada NDC" | Fan-out por documento [F4] |
| `comparative` | "Comparar emisiones entre países" | Hybrid per-document |
| `panorama` | "Dame un panorama de la biblioteca" | Hybrid + budget amplio |

### 8.3 Citas `[#N]`

Las respuestas del asistente incluyen referencias `[#N]` (ej. `[#1]`, `[#2]`).
El frontend las resuelve así:

```js
// 1. Parsear los índices del texto
const indices = [...answer.matchAll(/\[#(\d+)\]/g)].map(m => parseInt(m[1]))

// 2. Cruzar con metadata.citations
const citation = metadata.citations.find(c => c.index === idx)
// → { index, chunk_id, chunk_index, document_slug, document_name, page_number }

// 3. Obtener el texto del chunk para el panel lateral
GET /api/document/{citation.document_slug}/chunks/{citation.chunk_index}/
```

---

## 9. SSE — protocolo de streaming

`POST /api/chat/messages/stream/`

El endpoint devuelve un stream `text/event-stream`. Cada evento tiene la forma:

```
data: {"type": "...", ...}\n\n
```

### Tipos de evento

| Tipo | Payload | Momento |
|---|---|---|
| `user_message` | `{ type, message: ChatMessageSerializer }` | Inmediatamente al recibir la request |
| `status` | `{ type, phase: "retrieval", detail: "Preparando contexto..." }` | Antes de la generación |
| `chunk` | `{ type, content: "texto parcial" }` | Por cada token generado |
| `done` | `{ type, message: ChatMessageSerializer }` | Al finalizar — contiene el mensaje completo con citas y metadata |
| `error` | `{ type, detail: "mensaje de error" }` | Si ocurre un error |

### Implementación en el frontend

```js
const response = await fetch('/api/chat/messages/stream/', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${accessToken}`
  },
  body: JSON.stringify({ session: sessionId, content: userMessage })
})

const reader = response.body.getReader()
const decoder = new TextDecoder()
let buffer = ''

while (true) {
  const { done, value } = await reader.read()
  if (done) break

  buffer += decoder.decode(value, { stream: true })
  const lines = buffer.split('\n\n')
  buffer = lines.pop() // guarda el fragmento incompleto

  for (const line of lines) {
    if (!line.startsWith('data: ')) continue
    const event = JSON.parse(line.slice(6))

    switch (event.type) {
      case 'user_message':
        // mostrar el mensaje del usuario en la UI
        break
      case 'status':
        // mostrar indicador de carga ("Recuperando contexto...")
        break
      case 'chunk':
        // append al texto del asistente que se está construyendo
        assistantText += event.content
        break
      case 'done':
        // reemplazar con el mensaje final (tiene citas y metadata completos)
        finalMessage = event.message
        break
      case 'error':
        // mostrar error al usuario
        break
    }
  }
}
```

---

## 10. Códigos de error comunes

| Código | Cuándo ocurre |
|---|---|
| `400` | Validación fallida — el body de la respuesta tiene los campos con error |
| `401` | Token ausente, expirado o inválido |
| `403` | Sin permisos sobre el recurso (no es owner, no tiene rol) |
| `404` | Recurso no encontrado o sin permisos de lectura |
| `413` | Archivo demasiado grande en upload |
| `429` | Rate limit del proveedor de IA (OpenAI / Anthropic) |
| `500` | Error interno — revisar logs en `/ecs/ecofilia-api` |
| `503` | Worker Celery caído — chunking/embeddings no procesan |

### Formato de error de validación (400)

```json
{
  "email": ["Enter a valid email address."],
  "document_slugs": ["Documentos no encontrados: ndc-inexistente"]
}
```

### Error de chat (400 con código específico)

```json
{ "detail": "Error de autenticación con el proveedor de IA. Verifica la configuración de la API key." }
```

---

## Apéndice — Variables de entorno que afectan el comportamiento del motor

> Solo relevante para el equipo técnico. El frontend no necesita conocerlas,
> pero ayudan a entender por qué el motor responde diferente en distintos entornos.

| Variable | Default | Efecto visible en la API |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `anthropic` → respuestas más elaboradas, `model` en sesiones nuevas será `claude-sonnet-4-6` |
| `RAG_RECALL_MODE` | `1` | `0` = el motor descarta evidencia de baja similitud (comportamiento viejo) |
| `RAG_PARENT_EXPANSION` | `1` | `0` = no expande fragmentos a pasajes contiguos |
| `RAG_FANOUT_ENABLED` | `1` | `0` = "extraé X de cada documento" usa una sola pasada (menos preciso) |
| `RAG_AUTO_STRATEGY` | `1` | `0` = skills/evaluaciones usan estrategia fija en vez del router |
| `CHAT_CONTEXT_CHUNKS` | `8` | Chunks base en el contexto del LLM |
| `RAG_MAX_CONTEXT_CHUNKS` | `24` | Tope del budget adaptativo |
