# Dependencies — Thermia

## Direct Dependencies (from `requirements.txt`)

| Package | Version Constraint | Role in Application | Migration Impact |
|---------|-------------------|---------------------|------------------|
| `fastapi` | `>=0.115.0` | REST API framework | None |
| `uvicorn[standard]` | `>=0.32.0` | ASGI server | None |
| `sqlalchemy` | `>=2.0.0` | ORM and query building | None |
| `alembic` | `>=1.14.0` | Database migrations | None |
| `pgvector` | `>=0.3.0` | pgvector SQLAlchemy integration for `Vector(1024)` | None |
| `psycopg2-binary` | `>=2.9.0` | PostgreSQL database driver | None |
| `sshtunnel` | `>=0.4.0` | SSH tunnel for local dev DB access | None |
| `paramiko` | `<3` | SSH protocol (pinned for sshtunnel compat) | None |
| `python-dotenv` | `>=1.0.0` | Load `.env` into process environment | None |
| `pytest` | `>=8.0.0` | Test framework | None |
| `pytest-mock` | `>=3.14.0` | Mocking utilities for tests | None |
| `httpx` | `>=0.27.0` | HTTP client for FastAPI TestClient | None |
| **`cohere`** | **`>=5.0.0`** | **Cohere API client for embedding generation** | **REMOVE** |
| `gitpython` | `>=3.1.0` | Clone/pull legal corpus repo | None |
| `tiktoken` | `>=0.7.0` | OpenAI token counting for article chunking | None |
| `pdfplumber` | `>=0.11.0` | PDF text extraction | None |
| `langchain` | `>=0.3.0` | LangChain orchestration for LLM calls | None |
| `langchain-groq` | `>=0.2.0` | Groq integration for LangChain | None |
| `python-multipart` | `>=0.0.12` | Multipart form parsing for PDF upload | None |
| `slowapi` | `>=0.1.9` | Rate limiting middleware | None |
| `PyYAML` | `>=6.0` | YAML frontmatter parsing in legal markdown files | None |

## Dependency Changes Required for bge-m3 Migration

### Remove
| Package | Reason |
|---------|--------|
| `cohere` | Replaced by direct HTTP POST to Ollama API |

### Add
| Package | Reason |
|---------|--------|
| `requests` (stdlib or package) | HTTP calls to Ollama `/api/embeddings` endpoint (or use `httpx`) |

### Keep (unchanged)
All other dependencies stay — the migration only affects the embedding provider.

## Transitive / Implicit Dependencies

| Package | Used Via | Purpose |
|---------|----------|---------|
| `cryptography` | paramiko | SSH tunnel encryption |
| `starlette` | fastapi | ASGI toolkit |
| `pydantic` | fastapi | Data validation |
| `anyio` | fastapi | Async runtime |
| `sniffio` | fastapi, anyio | Async library detection |
| `typing_extensions` | fastapi, sqlalchemy | Type hints |
| `greenlet` | sqlalchemy | Coroutine support |
| `yarl` | aiohttp/aioify | URL handling |
| `MarkupSafe` | jinja2 (langchain) | Template safety |

## System Dependencies

| Dependency | Purpose |
|------------|---------|
| PostgreSQL ≥ 14 with pgvector extension | Document storage and vector search |
| Docker (deployment) | Container runtime |
| Git | Repository cloning for ingestion |

## Ollama Migration — New Dependency

**Target Service**: `https://ollama.cvbooster.es/api/embeddings`
- **Protocol**: HTTP POST
- **Model**: `bge-m3` (BAAI General Embedding)
- **Dimension**: 1024
- **Auth**: None (self-hosted)
- **Rate Limits**: None (self-hosted)
- **Payload Format**:
  ```json
  {
    "model": "bge-m3",
    "prompt": "text to embed"
  }
  ```
- **Response Format**:
  ```json
  {
    "embedding": [0.1, 0.2, ...]
  }
  ```
