# FinRAG Enterprise
## AI-Powered Financial Document Intelligence Platform

### Quick Start
```bash
cp .env.example .env          # fill secrets
docker compose up -d          # start all services
docker compose exec backend alembic upgrade head   # run migrations
```

### Service URLs
| Service | URL |
|---|---|
| Admin Portal | http://localhost:3000 |
| Chat UI | http://localhost:3001 |
| API Docs | http://localhost:8000/docs |
| Weaviate Console | http://localhost:8080 |
| Grafana | http://localhost:3100 |
| Prometheus | http://localhost:9090 |

### Architecture
```
finrag/
├── backend/           FastAPI + Celery (Python 3.12)
├── frontend/admin/    Admin Portal (React 18)
├── frontend/chat/     Chat UI (React 18)
├── docker/            Dockerfiles
├── infra/             Nginx, Prometheus, Grafana
└── scripts/           Dev & ops utilities
```

### Phase Build Order
0. Foundation (this repo, Docker, DB schema, auth)
1. Ingestion Pipeline (upload API, Celery workers)
2. OCR + Parser (PaddleOCR, layout parser)
3. Embedding + Weaviate (chunking, indexing)
4. Retrieval Engine (hybrid BM25 + vector, re-rank)
5. Chat Orchestrator (LangChain, streaming SSE)
6. Frontend (Admin Portal + Chat UI)
7. Security (RBAC, audit chain, TLS)
8. Quality (RAGAS, load tests, monitoring)
