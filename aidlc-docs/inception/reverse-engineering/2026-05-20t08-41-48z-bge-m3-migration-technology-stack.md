# Technology Stack — Thermia

## Languages

| Language | Version | Usage |
|----------|---------|-------|
| Python | 3.12 (container base: `python:3.12-slim`) | Backend application, ingestion script, all business logic |
| SQL | PostgreSQL dialect | Database queries, pgvector operations, tsvector |
| YAML/JSON | — | Configuration, metadata, .env.example |
| Markdown | — | Legal corpus source files (legalize-es repo) |

## Frameworks & Libraries

### Web Framework

| Library | Version (approx.) | Purpose |
|---------|-------------------|---------|
| `fastapi` | ≥0.115.0 | REST API framework with async support |
| `uvicorn[standard]` | ≥0.32.0 | ASGI server |
| `slowapi` | ≥0.1.9 | Rate limiting middleware |
| `python-multipart` | ≥0.0.12 | Multipart form parsing for PDF upload |
| `httpx` | ≥0.27.0 | Async HTTP client (testing) |
| `pydantic` | (FastAPI dep) | Data validation |

### Database

| Library | Version (approx.) | Purpose |
|---------|-------------------|---------|
| `sqlalchemy` | ≥2.0.0 | ORM and query building |
| `alembic` | ≥1.14.0 | Database migration management |
| `pgvector` | ≥0.3.0 | PostgreSQL vector extension support for SQLAlchemy |
| `psycopg2-binary` | ≥2.9.0 | PostgreSQL driver |
| `sshtunnel` | ≥0.4.0 | SSH tunnel for local development |
| `paramiko` | <3 | SSH protocol library (sshtunnel dependency) |

### Embedding (Current — Migration Target)

| Library | Version (approx.) | Purpose |
|---------|-------------------|---------|
| `cohere` | ≥5.0.0 | Cohere API client for `embed-multilingual-v3.0` |

### LLM

| Library | Version (approx.) | Purpose |
|---------|-------------------|---------|
| `langchain` | ≥0.3.0 | LangChain orchestration framework |
| `langchain-groq` | ≥0.2.0 | Groq model integration for LangChain |

### PDF Processing

| Library | Version (approx.) | Purpose |
|---------|-------------------|---------|
| `pdfplumber` | ≥0.11.0 | PDF text extraction |

### Ingestion

| Library | Version (approx.) | Purpose |
|---------|-------------------|---------|
| `gitpython` | ≥3.1.0 | Git operations (clone/pull legal corpus) |
| `tiktoken` | ≥0.7.0 | OpenAI token counting for chunking strategy |
| `PyYAML` | ≥6.0 | YAML frontmatter parsing in legal markdown files |

### Testing

| Library | Version (approx.) | Purpose |
|---------|-------------------|---------|
| `pytest` | ≥8.0.0 | Test framework |
| `pytest-mock` | ≥3.14.0 | Mocking utilities |

## Runtime Environment

| Component | Detail |
|-----------|--------|
| **Container** | Docker (python:3.12-slim) |
| **Port** | 8000 |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| **Process Model** | ASGI with `asyncio.to_thread()` for blocking DB/API calls |
| **OS** | Linux (Debian-based slim) / macOS (development) |

## External Services

| Service | Purpose | Cost Model | Status |
|---------|---------|------------|--------|
| **Cohere API** | Text embeddings (`embed-multilingual-v3.0`) | Per-request pricing | **LEAVING** |
| **Groq API** | LLM inference (`llama-3.1-8b-instant`) | Free tier / quota-based | **STAYING** |
| **PostgreSQL** | Document storage + vector search | Self-hosted | **STAYING** |
| **legalize-es repo** | Source legal corpus (Spanish law markdown) | Open source | **STAYING** |

## Infrastructure (Target State Post-Migration)

| Component | Technology | Details |
|-----------|------------|---------|
| **Embedding Service** | Ollama with bge-m3 | `https://ollama.cvbooster.es/api/embeddings` |
| **LLM Service** | Groq API | Unchanged |
| **Database** | PostgreSQL + pgvector | Unchanged |
| **CI/CD** | (Not specified) | — |

## Observability

| Aspect | Implementation |
|--------|---------------|
| **Logging** | Python `logging` module, structured log format (`key_pool.rotated`, etc.) |
| **Error Tracking** | Exception propagation to FastAPI exception handlers |
| **Auth Logging** | HMAC comparison, no PII in logs |
| **Key Leak Prevention** | SHA256 hashed keys in logs (first 8 hex chars) |

## Development Environment

| Tool | Detail |
|------|--------|
| **Context** | Python 3.12 virtualenv |
| **Env Management** | python-dotenv (.env file) |
| **Test Runner** | pytest |
| **Mocking** | unittest.mock.MagicMock |
| **VCS** | Git with conventional commits |
