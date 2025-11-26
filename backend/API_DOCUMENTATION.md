# Ecofilia API Documentation

## Base URLs
```
Document APIs:    http://localhost/api/document/
Chat APIs:        http://localhost/api/chat/
Projects APIs:    http://localhost/api/projects/
Evaluations APIs: http://localhost/api/evaluations/
```

Replace `localhost` with your actual domain/hostname when deploying.

## Authentication
All endpoints require authentication. Use either:
- **Token Authentication** - Recommended for programmatic access: `Authorization: Token <your-token>`
- **Session Authentication** - For browser-based requests
- **Basic Authentication** - For programmatic access (username:password)

---

## Endpoints

### 1. RAG Query Endpoint

Perform semantic search queries on document chunks using vector similarity.

**Endpoint:** `GET /api/document/rag/`

**Authentication:** Required (Token, Session, or Basic)

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | The search query text |
| `documents` | string[] | No | Filter results to specific document slugs (can be repeated) |
| `public` | string | No | Filter by document visibility. Values: `"true"` or `"false"` |

**Example Requests:**

```bash
# Basic query
curl -X GET "http://localhost/api/document/rag/?query=climate change" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Query with document filter
curl -X GET "http://localhost/api/document/rag/?query=climate change&documents=report-2023&documents=analysis-2024" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Query for public documents only
curl -X GET "http://localhost/api/document/rag/?query=climate change&public=true" \
  -H "Authorization: Token YOUR_TOKEN_HERE"
```

**Response:** `200 OK`

```json
{
  "query": "climate change",
  "results": [
    {
      "id": 1,
      "content": "The impact of climate change on biodiversity...",
      "chunk_index": 0,
      "document_id": 5,
      "token_count": 120,
      "embedding": [0.123, 0.456, ...],
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

**Error Responses:**

- `400 Bad Request` - Missing or invalid query parameter
  ```json
  {
    "error": "Missing query parameter"
  }
  ```

- `401 Unauthorized` - Authentication required

- `500 Internal Server Error` - Server error
  ```json
  {
    "error": "Error message details"
  }
  ```

**Permission Rules:**
- **Regular users:** Can query only their own documents or public documents
- **Staff users:** Can query all documents

---

### 2. Create Document Endpoint

Upload and create a new document. The document will be automatically processed and chunked in the background.

**Endpoint:** `POST /api/document/create/`

**Authentication:** Required (Token, Session, or Basic)

**Request Body:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | Yes | The document file to upload |

**Example Request:**

```bash
curl -X POST "http://localhost/api/document/create/" \
  -H "Authorization: Token YOUR_TOKEN_HERE" \
  -F "file=@/path/to/document.pdf"
```

**Response:** `201 Created`

```json
{
  "slug": "my-document-2024",
  "name": "my-document-2024",
  "category": "",
  "description": "",
  "file": "/media/documents/my-document-2024.pdf"
}
```

**Error Responses:**

- `400 Bad Request` - File is required or validation failed
  ```json
  {
    "file": ["File is required."]
  }
  ```

- `401 Unauthorized` - Authentication required

**Notes:**
- The uploaded file is automatically saved with the logged-in user as the owner
- Document name and slug are automatically generated from the filename
- Processing happens asynchronously in the background
- You can immediately upload another file after successful creation

---

### 3. List Documents Endpoint

Retrieve a list of documents with optional filtering.

**Endpoint:** `GET /api/document/list/`

**Authentication:** Required (Token, Session, or Basic)

**Query Parameters (Filters):**

All filters use Django REST Framework's filtering syntax:

| Filter | Type | Operations | Description |
|--------|------|------------|-------------|
| `slug` | string | `exact`, `icontains` | Filter by document slug |
| `name` | string | `exact`, `icontains` | Filter by document name |
| `category` | string | `exact`, `icontains` | Filter by category |
| `extracted_text` | string | `icontains` | Search in extracted text |
| `chunking_status` | string | `exact` | Filter by chunking status (pending, processing, done, error) |
| `created_at` | date | `exact`, `year__gt`, `year__lt` | Filter by creation date |
| `is_public` | boolean | `exact` | Filter by public visibility |

**Example Requests:**

```bash
# List all user's documents
curl -X GET "http://localhost/api/document/list/" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Filter by name
curl -X GET "http://localhost/api/document/list/?name__icontains=report" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Filter by category
curl -X GET "http://localhost/api/document/list/?category__exact=research" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Filter by chunking status
curl -X GET "http://localhost/api/document/list/?chunking_status=done" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Search in content
curl -X GET "http://localhost/api/document/list/?extracted_text__icontains=climate" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Filter by date (documents created after 2023)
curl -X GET "http://localhost/api/document/list/?created_at__year__gt=2023" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Filter by public documents only
curl -X GET "http://localhost/api/document/list/?is_public=true" \
  -H "Authorization: Token YOUR_TOKEN_HERE"

# Combined filters
curl -X GET "http://localhost/api/document/list/?chunking_status=done&is_public=true&name__icontains=report" \
  -H "Authorization: Token YOUR_TOKEN_HERE"
```

**Response:** `200 OK`

```json
[
  {
    "slug": "research-paper-2024",
    "name": "research-paper-2024",
    "category": "research",
    "description": "Annual research findings",
    "file": "/media/documents/research-paper-2024.pdf"
  },
  {
    "slug": "analysis-q1-2024",
    "name": "analysis-q1-2024",
    "category": "analysis",
    "description": "",
    "file": "/media/documents/analysis-q1-2024.pdf"
  }
]
```

**Error Responses:**

- `401 Unauthorized` - Authentication required

**Permission Rules:**
- **Regular users:** Can only see their own documents
- **Staff users:** Can see all documents

---

### 4. Chat Sessions Endpoint

Create and manage chat sessions that define which documents can be used as context.

**Create Session:** `POST /api/chat/sessions/`

**Authentication:** Required (Token, Session, or Basic)

**Request Body (JSON):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Display name for the session |
| `document_slugs` | string[] | Yes | Slugs of documents the assistant may use |
| `system_prompt` | string | No | Override default assistant instructions |
| `model` | string | No | OpenAI model (defaults to `MODEL_COMPLETION`) |
| `temperature` | float | No | Creativity (0-1, default `0.1`) |
| `language` | string | No | Session language hint |

**Example Request:**

```bash
curl -X POST "http://localhost/api/chat/sessions/" \
  -H "Authorization: Token YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
        "title": "Reporte de sostenibilidad",
        "document_slugs": ["reporte-2024"],
        "temperature": 0.2
      }'
```

**Response:** `201 Created`

```json
{
  "id": 5,
  "title": "Reporte de sostenibilidad",
  "system_prompt": "Eres un asistente...",
  "model": "gpt-4o-mini",
  "temperature": 0.2,
  "language": "es",
  "is_active": true,
  "created_at": "2025-02-01T13:10:00Z",
  "updated_at": "2025-02-01T13:10:00Z",
  "document_slugs": ["reporte-2024"]
}
```

**List Sessions:** `GET /api/chat/sessions/` – returns only the sessions owned by the authenticated user (staff users can see all sessions).

**Security Notes:**
- Users can only attach documents they own or documents marked as public.
- Once created, every message in the session is restricted to the pre-approved documents.

---

### 5. Chat Messages Endpoint

Send a message within a session and receive the AI response enriched with document chunks.

**Endpoint:** `POST /api/chat/messages/`

**Authentication:** Required

**Request Body (JSON):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session` | integer | Yes | ID of an existing chat session |
| `content` | string | Yes | User message/question |

**Example Request:**

```bash
curl -X POST "http://localhost/api/chat/messages/" \
  -H "Authorization: Token YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
        "session": 5,
        "content": "¿Cuáles son los objetivos principales del reporte?"
      }'
```

**Response:** `201 Created`

```json
{
  "user_message": {
    "id": 12,
    "session": 5,
    "role": "user",
    "content": "¿Cuáles son los objetivos principales del reporte?",
    "chunk_ids": [],
    "chunks": [],
    "metadata": {},
    "created_at": "2025-02-01T13:15:00Z"
  },
  "assistant_message": {
    "id": 13,
    "session": 5,
    "role": "assistant",
    "content": "El reporte prioriza reducir emisiones en 30%...",
    "chunk_ids": [45, 47],
    "chunks": [
      {
        "id": 45,
        "document_slug": "reporte-2024",
        "document_name": "Reporte 2024",
        "chunk_index": 3,
        "content": "Objetivos principales..."
      }
    ],
    "metadata": {
      "usage": {
        "total_tokens": 220
      }
    },
    "created_at": "2025-02-01T13:15:01Z"
  }
}
```

**Error Responses:**
- `400 Bad Request` – Session without documents, validation error, or missing content.
- `403 Forbidden` – Attempting to use a session owned by another user (non-staff).
- `502 Bad Gateway` – OpenAI temporarily unavailable.

**Permission Rules:**
- Messages can only be sent by the session owner (staff members can act on any session).
- Chunks returned in `chunks` always belong to the documents tied to the session.

---

## Data Models

### Document Model

```json
{
  "slug": "unique-identifier",
  "name": "Document Name",
  "category": "Category",
  "description": "Description",
  "file": "/media/documents/filename.pdf"
}
```

**Note:** The following fields are automatically set and not returned in the API:
- `owner` - Set automatically to the authenticated user
- `created_at` - Set automatically
- `extracted_text` - Extracted during processing
- `chunking_status` - Tracks processing status (pending, processing, done, error)
- `chunking_done` - Boolean flag for completion
- `chunking_offset` - Processing progress
- `last_error` - Error messages if processing fails
- `retry_count` - Number of retry attempts
- `is_public` - Public visibility flag

### SmartChunk Model

```json
{
  "id": 1,
  "content": "Chunk content text...",
  "chunk_index": 0,
  "document_id": 5,
  "token_count": 150,
  "embedding": [0.123, 0.456, 0.789, ...],
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

### 4. Evaluations API (nuevo)

Centraliza la definición de pilares/KPIs, control de acceso y ejecución sobre proyectos.

**Base endpoint:** `http://localhost/api/evaluations/`

#### 4.1 Crear/listar evaluaciones

`GET /api/evaluations/` — Lista solo las evaluaciones donde el usuario es dueño, tiene permisos compartidos o son públicas.  
`POST /api/evaluations/` — Crea una evaluación completa.

```json
{
  "title": "Evaluación ESG 2025",
  "visibility": "private",
  "project_slug": "proyecto-demo",      // opcional
  "document_slugs": ["doc-1", "doc-2"],  // opcional si el proyecto ya tiene docs
  "pillars": [
    {
      "title": "Impacto ambiental",
      "context_instructions": "Revisar emisiones Scope 1 y 2.",
      "metrics": [
        {
          "title": "Emisiones totales",
          "instructions": "Resumir emisiones reportadas.",
          "response_type": "qualitative"
        },
        {
          "title": "Calificación emisiones",
          "instructions": "Asignar un puntaje 0-5",
          "response_type": "quantitative",
          "scale_min": 0,
          "scale_max": 5
        }
      ]
    }
  ]
}
```

La respuesta incluye los pilares/metricas creados, documentos adjuntos y metadatos del dueño.

#### 4.2 Compartir evaluaciones

- `GET /api/evaluations/{slug}/shares/` — lista de usuarios con acceso (solo owner/staff).  
- `POST /api/evaluations/{slug}/shares/` — agrega o actualiza un usuario `{ "user_id": 42, "role": "editor" }`.  
- `PATCH/DELETE /api/evaluations/{slug}/shares/{share_id}/` — cambia el rol o revoca acceso.

Roles permitidos:
- `viewer`: solo lectura/ejecución.
- `editor`: puede editar definición y ejecutar runs.

#### 4.3 Ejecutar una evaluación

`POST /api/evaluations/{slug}/runs/`

```json
{
  "project_slug": "proyecto-demo",     // opcional, usa el que tenga la evaluación
  "document_slugs": ["doc-3"],         // opcional para sobrescribir documentos
  "model": "gpt-4o-mini",              // opcional, hereda de la evaluación
  "temperature": 0.1,
  "language": "es",
  "instructions_override": "Enfocar en Q3 2024."
}
```

La API crea un `run`, construye un snapshot de documentos (proyecto, evaluación o payload) y encola la tarea Celery `run_evaluation_task`. La respuesta vuelve inmediatamente con el estado `pending`:

```json
{
  "id": 17,
  "status": "pending",
  "document_snapshot": [
    {"slug": "doc-1", "name": "Reporte 2024"}
  ],
  "pillar_results": []
}
```

#### 4.4 Consultar runs

- `GET /api/evaluations/{slug}/runs/` — historial (ordenado por fecha más reciente).  
- `GET /api/evaluations/{slug}/runs/{run_id}/` — detalle con los pilares/métricas evaluados una vez que `status` sea `completed` o `failed`.

Ejemplo de respuesta cuando finaliza:

```json
{
  "id": 17,
  "status": "completed",
  "error_message": "",
  "pillar_results": [
    {
      "pillar": 3,
      "summary": "Resultados del pilar Impacto ambiental.",
      "metric_results": [
        {
          "metric": 8,
          "response_type": "quantitative",
          "response_text": "Calificación 4/5 respaldada en los fragmentos indicados.",
          "response_value": 4.0,
          "chunk_ids": [42, 43],
          "sources": [
            {"document_slug": "doc-1", "chunk_index": 10}
          ]
        }
      ]
    }
  ]
}
```

Si ocurre un error del LLM/RAG el estado queda en `failed` y `error_message` describe el motivo.

---

## Usage Examples

### JavaScript/TypeScript (with Fetch)

```javascript
const API_TOKEN = 'YOUR_TOKEN_HERE';

// RAG Query
async function searchDocuments(query) {
  const response = await fetch(
    `http://localhost/api/document/rag/?query=${encodeURIComponent(query)}`,
    {
      headers: {
        'Authorization': `Token ${API_TOKEN}`
      }
    }
  );
  return await response.json();
}

// Upload Document
async function uploadDocument(file) {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch(
    'http://localhost/api/document/create/',
    {
      method: 'POST',
      headers: {
        'Authorization': `Token ${API_TOKEN}`
      },
      body: formData
    }
  );
  return await response.json();
}

// List Documents
async function listDocuments(filters = {}) {
  const params = new URLSearchParams(filters);
  const response = await fetch(
    `http://localhost/api/document/list/?${params}`,
    {
      headers: {
        'Authorization': `Token ${API_TOKEN}`
      }
    }
  );
  return await response.json();
}
```

### Python (with requests)

```python
import requests

BASE_URL = "http://localhost/api/document"
API_TOKEN = "YOUR_TOKEN_HERE"

headers = {
    "Authorization": f"Token {API_TOKEN}"
}

# RAG Query
def search_documents(query):
    response = requests.get(
        f"{BASE_URL}/rag/",
        params={"query": query},
        headers=headers
    )
    return response.json()

# Upload Document
def upload_document(file_path):
    with open(file_path, 'rb') as f:
        files = {'file': f}
        response = requests.post(
            f"{BASE_URL}/create/",
            files=files,
            headers=headers
        )
    return response.json()

# List Documents
def list_documents(filters=None):
    response = requests.get(
        f"{BASE_URL}/list/",
        params=filters or {},
        headers=headers
    )
    return response.json()
```

---

## Browser-Based API Interface

You can access the interactive API documentation at:
```
http://localhost/api/document/
```

This provides a browsable API interface where you can:
- Test endpoints directly in your browser
- View request/response formats
- Upload files using an HTML form
- See authentication options

---

## Notes

- All times are in UTC unless otherwise specified
- File uploads support any file type, but text extraction depends on the file format
- Vector embeddings are 1536-dimensional (OpenAI standard)
- The RAG query endpoint returns the top 5 most similar chunks by default
- Document processing happens asynchronously; check `chunking_status` to monitor progress

