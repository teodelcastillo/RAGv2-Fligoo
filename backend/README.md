# Ecofilia Backend

Django-based document management system with RAG (Retrieval-Augmented Generation) capabilities. Upload documents, process them with OpenAI embeddings, and search semantically using PostgreSQL with pgvector.

## Quick Start

### Prerequisites
- Docker & Docker Compose
- OpenAI API key

### Setup
```bash
# 1. Configure environment
cp docker/template.env docker/.env
# Edit docker/.env with your settings

# 2. Start services
docker-compose up -d

# 3. Run migrations
docker-compose exec backend python manage.py migrate

# 4. Create superuser
docker-compose exec backend python manage.py createsuperuser
```

### Access
- API: http://localhost/api/document/
- Admin: http://localhost/admin/

## Documentation

- **[Technical Documentation](./TECHNICAL_DOCUMENTATION.md)** - Architecture, development setup, troubleshooting
- **[API Documentation](./API_DOCUMENTATION.md)** - Complete API reference with examples

## Tech Stack

**Backend:** Django 5.2+, Django REST Framework  
**Database:** PostgreSQL 16 + pgvector  
**Task Queue:** Celery + AWS SQS  
**Storage:** AWS S3 (production) / Local filesystem (dev)  
**Embeddings:** OpenAI API  
**Containerization:** Docker, Docker Compose

## Key Features

- 📄 Document upload & processing (PDF, DOCX)
- 🧠 Automatic text chunking with OpenAI embeddings
- 🔍 Vector similarity search using pgvector
- 🔄 Background processing with Celery
- 🌐 RESTful API with browsable interface
- ☁️ AWS S3 integration for file storage

## Development

```bash
# Start development environment
docker-compose up

# Run tests
docker-compose exec backend python manage.py test

# Django shell
docker-compose exec backend python manage.py shell

# View logs
docker-compose logs -f backend
```

For more details, see [Technical Documentation](./TECHNICAL_DOCUMENTATION.md).
