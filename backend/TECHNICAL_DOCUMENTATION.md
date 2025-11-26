# Ecofilia - Technical Documentation

## Project Overview

Ecofilia is a Django-based document management and retrieval system with RAG (Retrieval-Augmented Generation) capabilities. It allows users to upload documents, automatically processes and chunks them with OpenAI embeddings, and provides semantic search functionality using PostgreSQL with pgvector extension.

### Key Features
- Document upload and processing
- Automatic text extraction (PDF, DOCX)
- Intelligent text chunking with embeddings
- Semantic search using vector similarity
- Conversational AI chat with RAG context
- RESTful API with browsable interface
- Background task processing with Celery
- AWS S3 storage integration
- Docker containerization

---

## Technology Stack

### Core Technologies
- **Python 3.12+**
- **Django 5.2+**
- **PostgreSQL 16** with **pgvector extension**
- **Django REST Framework**
- **Celery 5.5+** for async task processing
- **OpenAI API** for embeddings
- **AWS S3** for file storage
- **AWS SQS** for Celery broker

### Development Tools
- **Poetry** for dependency management
- **Docker & Docker Compose** for containerization
- **Gunicorn** for production WSGI server
- **Nginx** for reverse proxy (production)
- **Boto3** for AWS services
- **Tiktoken** for token counting

### Key Libraries
- `django-cors-headers` - CORS handling
- `django-filter` - Advanced filtering
- `python-docx` - DOCX parsing
- `PyPDF2` - PDF parsing
- `openai` - Embeddings API
- `psycopg2-binary` - PostgreSQL adapter
- `django-storages` - S3 storage backend

---

## Project Structure

```
backend/
├── apps/
│   ├── document/          # Document management app
│   │   ├── api/           # API endpoints
│   │   │   ├── views.py   # ViewSets and API views
│   │   │   ├── serializers.py  # DRF serializers
│   │   │   ├── urls.py    # URL routing
│   │   │   └── filters.py # Query filtering
│   │   ├── models.py      # Document & SmartChunk models
│   │   ├── tasks.py       # Celery background tasks
│   │   ├── signals.py     # Django signals
│   │   └── utils/         # Utility modules
│   │       ├── chunker.py      # Text chunking logic
│   │       ├── client_openia.py  # OpenAI client
│   │       ├── parser.py       # File parsing
│   │       ├── query_filters.py  # Query filtering
│   │       └── client_tiktoken.py  # Token counting
│   ├── chat/              # Conversational RAG app
│   │   ├── api/           # Session & message endpoints
│   │   ├── services/      # RAG helpers and OpenAI orchestration
│   │   ├── models.py      # ChatSession & ChatMessage models
│   │   └── tests/         # API tests
│   └── user/              # Custom user app
│       └── models.py      # Custom User model
├── main/                   # Django project root
│   ├── settings/          # Environment-specific settings
│   │   ├── base.py       # Shared settings
│   │   ├── dev.py        # Development settings
│   │   └── prod.py       # Production settings
│   ├── celery.py         # Celery configuration
│   ├── urls.py           # Main URL configuration
│   ├── asgi.py           # ASGI config
│   └── wsgi.py           # WSGI config
├── docker/
│   ├── Dockerfile        # Backend container image
│   ├── entrypoint.sh     # Dev entrypoint
│   ├── entrypoint-prod.sh  # Production entrypoint
│   └── template.env      # Environment template
├── docker-compose.yml    # Local development setup
├── docker-compose-local.yml  # Alternative local config
├── docker-compose-prod.yml   # Production config
├── pyproject.toml        # Poetry dependencies
├── manage.py            # Django CLI
└── README.md            # Project README
```

---

## Architecture

### Architecture Diagram

![Ecofilia Architecture Diagram](./ecofilia-diagrama.png)

### System Components

#### 1. Web Application Layer
- **Django REST Framework** handles HTTP requests
- **Nginx** serves static files and reverse proxies (production)
- **Gunicorn** runs the Django application (production)

#### 2. Database Layer
- **PostgreSQL** with **pgvector** for vector storage
- Stores documents, chunks, and embeddings
- Vector similarity search using cosine distance

#### 3. Task Queue
- **Celery** workers process documents asynchronously
- **AWS SQS** as message broker
- Background processing for:
  - Document parsing
  - Text extraction
  - Chunking
  - Embedding generation
  - Evaluaciones (tarea `run_evaluation_task`)

#### 4. Storage
- **AWS S3** for file storage (production)
- Local filesystem for development

#### 5. External Services
- **OpenAI API** for generating embeddings

### Data Flow

#### Document Upload & Processing
```
1. User uploads file → POST /api/document/create/
2. Document model saved → Django signal triggered
3. Signal fires Celery task → process_document_chunks.delay(doc_id)
4. Celery worker picks up task from SQS
5. Worker downloads file from S3/local storage
6. Worker extracts text (parser.py)
7. Worker chunks text and generates embeddings (chunker.py)
8. Worker saves SmartChunk objects with embeddings
9. Worker updates Document.status to "done"
```

#### RAG Query Flow
```
1. User sends query → GET /api/document/rag/?query=...
2. API receives query → RAGQueryView
3. Generate query embedding → client_openia.embed_text()
4. Query database → SmartChunk.objects.top_similar(query_text)
5. PostgreSQL computes cosine distance
6. Returns top 5 similar chunks
7. API serializes and returns results
```

---

## Database Schema

### Document Model
```python
class Document(models.Model):
    owner = ForeignKey(User)           # Document owner
    name = CharField(255)              # Display name
    slug = SlugField(unique=True)     # URL-friendly identifier
    category = CharField(255)          # Document category
    description = TextField()          # Description
    file = FileField()                 # Uploaded file
    created_at = DateTimeField()       # Creation timestamp
    extracted_text = TextField()        # Extracted content
    chunking_status = CharField()      # Status: pending/processing/done/error
    chunking_offset = IntegerField()    # Processing offset
    chunking_done = BooleanField()     # Completion flag
    last_error = TextField()           # Error messages
    retry_count = IntegerField()       # Retry attempts
    is_public = BooleanField()         # Visibility flag
```

### SmartChunk Model
```python
class SmartChunk(models.Model):
    document = ForeignKey(Document)           # Parent document
    chunk_index = IntegerField()              # Position in document
    content = TextField()                     # Chunk text
    content_norm = GeneratedField()          # Normalized text (PostgreSQL generated)
    token_count = IntegerField()             # Token count
    title = CharField(255)                   # Chunk title
    summary = TextField()                    # Summary
    keywords = ArrayField(TextField)         # Extracted keywords
    embedding = VectorField(dimensions=1536) # OpenAI embedding vector
    created_at = DateTimeField()            # Creation timestamp
```

### Indexes
- Document: `slug` (unique), `owner`, `chunking_status`
- SmartChunk: `document_id`, `chunk_index`, `embedding` (vector similarity)

---

## Development Setup

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
- Poetry (for dependency management)
- PostgreSQL 16+ with pgvector extension
- OpenAI API key

### Local Development

1. **Clone the repository**
```bash
git clone <repository-url>
cd backend
```

2. **Set up environment**
```bash
# Copy environment template
cp docker/template.env docker/.env

# Edit .env with your configuration
nano docker/.env
```

Required environment variables:
```bash
SECRET_KEY=your-secret-key
DEBUG=True
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres1234
POSTGRES_NAME=postgres
POSTGRES_HOST=db
POSTGRES_PORT=5432
OPENAI_API_KEY=sk-your-key
MODEL_EMBEDDING=text-embedding-3-small
```

3. **Install dependencies with Poetry**
```bash
poetry install
poetry shell  # Activate virtual environment
```

4. **Run with Docker Compose**
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend

# Access Django shell
docker-compose exec backend python manage.py shell

# Run migrations
docker-compose exec backend python manage.py migrate

# Create superuser
docker-compose exec backend python manage.py createsuperuser
```

5. **Access the application**
- API: http://localhost/api/document/
- Admin: http://localhost/admin/
- DRF UI: http://localhost/api/document/ (browsable API)

### Without Docker (Poetry)
```bash
# Install dependencies
poetry install

# Set up local PostgreSQL
# Ensure pgvector extension is installed

# Activate environment
poetry shell

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver
```

---

## Development Workflow

### 1. Creating a New Feature

#### Add a New App
```bash
cd apps
python ../manage.py startapp myapp
```

Add to `INSTALLED_APPS` in `main/settings/base.py`:
```python
LOCAL_APPS = [
    "main",
    "apps.user",
    "apps.document",
    "apps.myapp",  # Add here
]
```

#### Create API Endpoints
1. Create serializers in `api/serializers.py`
2. Create views in `api/views.py`
3. Add URL routing in `api/urls.py`
4. Include URLs in main `urls.py`

Example:
```python
# apps/document/api/views.py
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

class MyView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    queryset = MyModel.objects.all()
    serializer_class = MySerializer
```

#### Create Model Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 2. Running Tests
```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test apps.document

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

### 3. Code Quality

#### Linting
```bash
# Install pre-commit hooks (if configured)
pre-commit install

# Run linters manually
flake8 apps/
black apps/
isort apps/
```

#### Type Checking
```bash
mypy .
```

### 4. Database Operations

#### Create Migration
```bash
python manage.py makemigrations
```

#### Apply Migrations
```bash
python manage.py migrate
```

#### Rollback Migration
```bash
python manage.py migrate app_name previous_migration_name
```

#### SQL Shell
```bash
python manage.py dbshell
```

### 5. Debugging

#### Django Shell
```bash
# Regular shell
python manage.py shell

# IPython shell (better)
python manage.py shell_plus

# Debug with print statements or IPython debugger
from IPython import embed; embed()
```

#### Logging
Check logs in Docker containers:
```bash
docker-compose logs -f backend
```

Django logging configured in settings:
```python
LOGGING = {
    'version': 1,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        }
    },
    'loggers': {
        'apps.document': {
            'handlers': ['console'],
            'level': 'DEBUG',
        }
    }
}
```

---

## Production Deployment

### Environment Configuration

Use `docker-compose-prod.yml` and configure:

```bash
# Production settings
DEBUG=False
SECRET_KEY=<strong-random-secret>
POSTGRES_HOST=production-db-host
AWS_STORAGE_BUCKET_NAME=your-s3-bucket
AWS_S3_REGION_NAME=us-east-1
SQS_QUEUE_URL=https://sqs.region.amazonaws.com/account/queue-name
OPENAI_API_KEY=sk-production-key
```

### AWS Resources Required

1. **S3 Bucket** for file storage
   - Set CORS policy for browser uploads
   - Configure IAM access

2. **SQS Queue** for Celery
   - Standard queue recommended
   - Configure visibility timeout (max task duration)
   - Dead letter queue for failed tasks

3. **PostgreSQL Database**
   - Enable pgvector extension
   - Configure backups
   - Set up read replicas if needed

### Deployment Steps

1. **Build production image**
```bash
docker build -f docker/Dockerfile -t ecofilia-backend:latest .
```

2. **Deploy with docker-compose**
```bash
docker-compose -f docker-compose-prod.yml up -d
```

3. **Run migrations**
```bash
docker-compose exec backend python manage.py migrate
```

4. **Collect static files**
```bash
docker-compose exec backend python manage.py collectstatic --noinput
```

5. **Setup Celery worker**
```bash
# Run Celery worker in separate container
celery -A main worker -l info --concurrency=4
```

### Monitoring

- Check application logs: `docker-compose logs -f backend`
- Monitor Celery tasks: Use Flower or CloudWatch
- Database monitoring: pgAdmin or CloudWatch RDS metrics
- API metrics: Add logging middleware or APM tools

---

## Key Modules & Utilities

### Document Processing (`apps/document/utils/`)

#### `parser.py`
- Extracts text from PDF and DOCX files
- Handles encoding issues
- Returns plain text for chunking

#### `chunker.py`
- Splits text into semantic chunks
- Generates OpenAI embeddings
- Creates SmartChunk objects with metadata
- Handles token limits

#### `client_openia.py`
- OpenAI API client wrapper
- Generates embeddings using `text-embedding-3-small`
- Error handling and retry logic

#### `client_tiktoken.py`
- Token counting for OpenAI models
- Ensures chunks stay within token limits
- Uses GPT-4 tokenizer by default

#### `query_filters.py`
- Advanced query filtering for RAG search
- Number extraction from queries
- Content normalization

### Background Tasks (`apps/document/tasks.py`)

#### `process_document_chunks()`
- Async Celery task for document processing
- Downloads file from S3/local storage
- Extracts, chunks, embeds text
- Handles errors and retries
- Updates Document status

**Task Configuration:**
- `max_retries=3`
- `default_retry_delay=30` seconds
- Uses `bind=True` for retry logic

### Signals (`apps/document/signals.py`)

#### `handle_document_post_save()`
- Triggers on Document creation
- Starts background processing
- In DEBUG mode: synchronous processing
- In production: async via Celery

---

## API Endpoints

See `API_DOCUMENTATION.md` for complete API reference.

### Key Endpoints
- `GET /api/document/rag/` - Semantic search
- `POST /api/document/create/` - Upload document
- `GET /api/document/list/` - List documents
- `POST /api/chat/sessions/` - Create chat session scoped to selected documents
- `POST /api/chat/messages/` - Send a message and receive RAG-powered responses

### Chat Module (`apps/chat/`)

- `ChatSession` / `ChatMessage` models guard chat ownership and document scope.
- `services/rag.py` limits retrieval to the session's approved documents and formats context.
- `api/views.py` exposes `/api/chat/sessions/` and `/api/chat/messages/`, orchestrating RAG + OpenAI Responses.
- Security: users can only reference their own or public documents; staff can access all sessions.

---

## Environment Variables

### Required Variables
```bash
SECRET_KEY           # Django secret key
DEBUG               # Boolean (True/False)
POSTGRES_USER       # Database user
POSTGRES_PASSWORD   # Database password
POSTGRES_NAME       # Database name
POSTGRES_HOST       # Database host
POSTGRES_PORT       # Database port
OPENAI_API_KEY      # OpenAI API key
MODEL_EMBEDDING     # Embedding model name
```

### Production Variables
```bash
AWS_STORAGE_BUCKET_NAME  # S3 bucket name
AWS_S3_REGION_NAME       # AWS region
SQS_QUEUE_URL           # Celery queue URL
```

### Optional Variables
```bash
DJANGO_SETTINGS_MODULE  # Settings module (auto-set)
CELERY_BROKER_URL       # Override broker URL
MODEL_COMPLETION        # Chat completion model (default gpt-4o-mini)
CHAT_CONTEXT_CHUNKS     # Max chunks sent per chat turn (default 4)
CHAT_HISTORY_MESSAGES   # Number of historic messages to send to OpenAI (default 10)
```

---

## Common Tasks & Troubleshooting

### Troubleshooting

#### Documents not processing
```bash
# Check Celery worker status
docker-compose logs celery-worker

# Check for errors in document status
python manage.py shell
>>> from apps.document.models import Document
>>> doc = Document.objects.get(slug='your-doc')
>>> print(doc.last_error)  # Check for errors
```

#### Vector search not working
```bash
# Verify pgvector extension
python manage.py dbshell
CREATE EXTENSION IF NOT EXISTS vector;

# Recreate embeddings
python manage.py shell
>>> from apps.document.tasks import process_document_chunks
>>> process_document_chunks(doc_id)
```

#### Authentication issues
```bash
# Create new superuser
python manage.py createsuperuser

# Change password
python manage.py changepassword username
```

### Database Maintenance

#### Backup Database
```bash
docker-compose exec db pg_dump -U postgres postgres > backup.sql
```

#### Restore Database
```bash
docker-compose exec -T db psql -U postgres postgres < backup.sql
```

#### Clear all data (dev only!)
```bash
docker-compose down -v  # Removes volumes
docker-compose up -d    # Recreates everything
```

### Celery Management

#### Purge queue
```bash
celery -A main purge
```

#### Check active tasks
```bash
celery -A main inspect active
```

#### Restart workers
```bash
docker-compose restart celery-worker
```

---

## Security Considerations

### Production Checklist
- [ ] Set `DEBUG=False`
- [ ] Use strong `SECRET_KEY`
- [ ] Configure `ALLOWED_HOSTS`
- [ ] Set up HTTPS/TLS
- [ ] Use secure cookie settings
- [ ] Configure CORS properly
- [ ] Enable database backups
- [ ] Use IAM roles (not keys) for AWS
- [ ] Rotate API keys regularly
- [ ] Enable database encryption at rest
- [ ] Set up rate limiting
- [ ] Monitor for security issues

### API Security
- All endpoints require authentication
- Session + Basic auth for browser
- Token auth for programmatic access
- Staff users have broader access
- Regular users see only their documents

---

## Performance Optimization

### Database
- Indexed fields: `slug`, `owner`, `chunking_status`
- Vector similarity uses pgvector index
- Consider read replicas for heavy queries

### Caching (Future)
- Cache frequently accessed documents
- Redis for session storage
- Query result caching

### Celery
- Adjust worker concurrency based on load
- Configure prefetch limits
- Set appropriate visibility timeout
- Use result backend for long-running tasks

### File Storage
- Use S3 transfer acceleration
- Enable CloudFront CDN
- Compress large files before upload

---

## Contributing

### Code Style
- Follow PEP 8
- Use Black for formatting
- Type hints for new code
- Docstrings for all functions/classes

### Git Workflow
```bash
# Create feature branch
git checkout -b feature/my-feature

# Commit changes
git add .
git commit -m "Add: description"

# Push and create PR
git push origin feature/my-feature
```

### Pull Request Process
1. Create feature branch from `main`
2. Write tests for new features
3. Ensure all tests pass
4. Update documentation
5. Create pull request
6. Code review required
7. Merge after approval

---

## Additional Resources

### Documentation
- [API Documentation](./API_DOCUMENTATION.md)
- [Django Documentation](https://docs.djangoproject.com/)
- [DRF Documentation](https://www.django-rest-framework.org/)
- [Celery Documentation](https://docs.celeryproject.org/)

### External Services
- [PostgreSQL pgvector](https://github.com/pgvector/pgvector)
- [OpenAI Embeddings](https://platform.openai.com/docs/guides/embeddings)
- [AWS S3](https://docs.aws.amazon.com/s3/)
- [AWS SQS](https://docs.aws.amazon.com/sqs/)

### Development Tools
- [Poetry](https://python-poetry.org/)
- [Docker Compose](https://docs.docker.com/compose/)
- [Django Debug Toolbar](https://django-debug-toolbar.readthedocs.io/)

---

## Getting Help

- Check logs: `docker-compose logs -f`
- Django shell: `python manage.py shell`
- Document models: See `apps/document/models.py`
- API issues: Check `API_DOCUMENTATION.md`
- Database issues: Check pgvector installation

## Project Status

- ✅ Document upload and storage
- ✅ Text extraction (PDF, DOCX)
- ✅ Intelligent chunking
- ✅ OpenAI embeddings
- ✅ Vector similarity search
- ✅ RESTful API
- ✅ Background processing
- ✅ AWS integration
- 🚧 Authentication improvements
- 🚧 Advanced search features
- 🚧 Analytics and monitoring
