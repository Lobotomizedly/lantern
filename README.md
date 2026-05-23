# Lantern - Narrative Intelligence Platform

Lantern is an advanced narrative intelligence platform that analyzes, extracts, and visualizes narratives from diverse data sources. It leverages state-of-the-art NLP, machine learning, and knowledge graph technologies to uncover hidden patterns, relationships, and insights within unstructured text data.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Quick Start](#quick-start)
- [Development Setup](#development-setup)
- [API Documentation](#api-documentation)
- [Development Workflow](#development-workflow)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

## Overview

Lantern transforms raw text data into actionable intelligence by:

- **Ingesting** documents from multiple sources (web, files, APIs)
- **Extracting** entities, relationships, and narrative elements
- **Analyzing** sentiment, themes, and narrative structures
- **Visualizing** knowledge graphs and narrative timelines
- **Alerting** on emerging narratives and trend changes

## Architecture

```
                                    +------------------+
                                    |   Frontend       |
                                    |   (Next.js)      |
                                    +--------+---------+
                                             |
                                             v
+------------------+              +----------+---------+              +------------------+
|   Data Sources   |              |      Backend       |              |   Storage        |
|                  +------------->|     (FastAPI)      +------------->|                  |
| - Web Scrapers   |              |                    |              | - PostgreSQL     |
| - RSS Feeds      |              | - REST API         |              |   (pgvector)     |
| - File Uploads   |              | - WebSocket        |              | - OpenSearch     |
| - External APIs  |              | - Auth/AuthZ       |              | - MinIO (S3)     |
+------------------+              +----------+---------+              | - Redis          |
                                             |                        +------------------+
                                             v
                    +------------------------+------------------------+
                    |                        |                        |
           +--------v--------+     +---------v-------+      +---------v-------+
           |   Workers       |     |    Temporal     |      |   ML Pipeline   |
           |   (Celery)      |     |   (Workflows)   |      |                 |
           |                 |     |                 |      | - NER           |
           | - Document Proc |     | - Orchestration |      | - Embeddings    |
           | - Entity Extract|     | - Long-running  |      | - Classification|
           | - Indexing      |     |   tasks         |      | - Summarization |
           +-----------------+     +-----------------+      +-----------------+

+-------------------------------------------------------------------------------------+
|                              Monitoring & Observability                             |
|  - Flower (Celery)  |  - Temporal UI  |  - OpenSearch Dashboards  |  - Prometheus  |
+-------------------------------------------------------------------------------------+
```

### Core Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Backend** | FastAPI | REST API, WebSocket, authentication |
| **Frontend** | Next.js | Interactive dashboard and visualizations |
| **Database** | PostgreSQL + pgvector | Structured data + vector embeddings |
| **Search** | OpenSearch | Full-text search and analytics |
| **Storage** | MinIO | Document and media file storage |
| **Cache** | Redis | Caching, sessions, task queue broker |
| **Workers** | Celery | Background task processing |
| **Workflows** | Temporal | Complex workflow orchestration |
| **ML Pipeline** | Transformers, spaCy | NLP and ML model inference |

## Features

### Document Processing
- Multi-format ingestion (PDF, DOCX, HTML, TXT, images)
- OCR for scanned documents
- Automatic language detection
- Content deduplication

### Entity Extraction
- Named Entity Recognition (NER)
- Entity resolution and deduplication
- Custom entity types
- Relationship extraction

### Narrative Analysis
- Claim and fact extraction
- Sentiment analysis
- Theme detection
- Narrative timeline construction

### Knowledge Graph
- Entity relationship mapping
- Graph visualization
- Path finding and clustering
- Temporal evolution tracking

### Search & Discovery
- Semantic vector search
- Full-text search with facets
- Similar document discovery
- Trend analysis

## Quick Start

### Prerequisites

- Docker and Docker Compose v2
- Git

### One-Command Setup

```bash
# Clone the repository
git clone https://github.com/lantern-ai/lantern.git
cd lantern

# Copy environment file
cp .env.example .env

# Start all services
docker compose up -d

# Wait for services to be healthy (about 2-3 minutes)
docker compose ps

# Access the application
# Frontend:     http://localhost:3000
# Backend API:  http://localhost:8000
# API Docs:     http://localhost:8000/docs
```

## Development Setup

### Backend Development

```bash
cd backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
make install-dev

# Run migrations
make migrate

# Start development server
make run-dev
```

### Frontend Development

```bash
cd frontend

# Install dependencies
npm install  # or: yarn install / pnpm install

# Start development server
npm run dev
```

### Running Tests

```bash
# Backend tests
cd backend
make test          # Run all tests
make test-cov      # Run with coverage
make test-fast     # Quick test run (no coverage)

# Frontend tests
cd frontend
npm run test       # Run unit tests
npm run test:e2e   # Run E2E tests
```

## API Documentation

The API documentation is available at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

### Authentication

Lantern uses JWT-based authentication. To authenticate:

```bash
# Get access token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password"}'

# Use token in requests
curl http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer <access_token>"
```

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | User authentication |
| GET | `/api/v1/projects` | List projects |
| POST | `/api/v1/projects` | Create project |
| POST | `/api/v1/documents` | Upload document |
| GET | `/api/v1/documents/{id}` | Get document details |
| POST | `/api/v1/search` | Search documents |
| GET | `/api/v1/entities` | List entities |
| GET | `/api/v1/narratives` | List narratives |
| GET | `/api/v1/graph` | Get knowledge graph |

## Development Workflow

### Code Quality

```bash
cd backend

# Run linter
make lint

# Format code
make format

# Type checking
make type-check

# Run all checks
make check
```

### Database Migrations

```bash
# Create new migration
make migrate-create name="add_user_preferences"

# Apply migrations
make migrate

# Rollback last migration
make migrate-down
```

### Docker Commands

```bash
# Build images
make docker-build

# Start services
make docker-up

# View logs
make docker-logs

# Stop services
make docker-down

# Shell into container
make docker-shell
```

## Project Structure

```
lantern/
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── api/            # API routes
│   │   │   └── v1/         # API version 1
│   │   ├── core/           # Core functionality
│   │   ├── models/         # SQLAlchemy models
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # Business logic
│   │   ├── worker/         # Celery tasks
│   │   └── main.py         # Application entry
│   ├── migrations/         # Alembic migrations
│   ├── tests/              # Test suite
│   ├── pyproject.toml      # Python dependencies
│   └── Makefile            # Development commands
│
├── frontend/               # Next.js frontend
│   ├── app/               # Next.js app router
│   ├── components/        # React components
│   ├── lib/               # Utilities
│   └── public/            # Static assets
│
├── infrastructure/         # Infrastructure configs
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   ├── Dockerfile.worker
│   └── init-db.sql
│
├── docker-compose.yml      # Development environment
├── .env.example           # Environment template
└── README.md              # This file
```

## Configuration

### Environment Variables

All configuration is done through environment variables. See `.env.example` for the complete list.

Key configurations:

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT` | Environment name | `development` |
| `SECRET_KEY` | JWT signing key | (required) |
| `DATABASE_URL` | PostgreSQL connection | (required) |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `OPENAI_API_KEY` | OpenAI API key | (optional) |
| `ANTHROPIC_API_KEY` | Anthropic API key | (optional) |

### Feature Flags

Enable/disable features via environment variables:

```bash
FEATURE_ML_EXTRACTION=true    # ML-based entity extraction
FEATURE_OCR_PROCESSING=true   # OCR for scanned documents
FEATURE_REALTIME_COLLAB=false # Real-time collaboration
```

## Deployment

### Production Checklist

- [ ] Set strong `SECRET_KEY` and `NEXTAUTH_SECRET`
- [ ] Configure SSL/TLS certificates
- [ ] Set `ENVIRONMENT=production`
- [ ] Disable `DEBUG` mode
- [ ] Configure proper CORS origins
- [ ] Set up monitoring and alerting
- [ ] Configure backup strategy
- [ ] Review security settings

### Kubernetes Deployment

See `infrastructure/k8s/` for Kubernetes manifests and Helm charts.

### Cloud Deployments

- **AWS**: Terraform modules in `infrastructure/terraform/aws/`
- **GCP**: Terraform modules in `infrastructure/terraform/gcp/`
- **Azure**: Terraform modules in `infrastructure/terraform/azure/`

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linting (`make check`)
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Code Style

- **Python**: Follow PEP 8, use Black for formatting, Ruff for linting
- **TypeScript**: Follow ESLint configuration, use Prettier
- **Commits**: Use conventional commits format

## License

This project is proprietary software. All rights reserved.

---

Built with care by the Lantern Team.
