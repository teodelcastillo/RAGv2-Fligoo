# Ecofilia RAG Project

This project is a Retrieval-Augmented Generation (RAG) system built for the Ecofilia application. It combines a Django backend with a vector database and OpenAI's language models to provide intelligent document search and Q&A capabilities.

## Project Structure

- **backend/**: Django project containing the core logic for vector storage, retrieval, and communication with the OpenAI API.
- **docker/**: Docker and Docker Compose configuration for local development.

---

## Documentation inside the backend folder

Refer to the `backend/README.md` file for detailed documentation, which includes:

- Django setup instructions
- PostgreSQL + pgvector configuration
- API endpoints and usage
- Environment variables and secrets

---

## Features

- 🔍 Semantic search using OpenAI's `text-embedding-3-small`
- 💾 Vector storage using PostgreSQL + pgvector
- 🤖 Chat-like interface for querying documents
- 🔐 Auth support (Token-based or via Django admin)
- 🐳 Dockerized for consistent development and deployment


