# Ecofilia API Documentation

## Base URL
```
http://localhost/api/document/
```

Or replace `localhost` with your actual domain/hostname.

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

