# Code Structure — Thermia

## Directory Tree

```
thermia-back/
├── Dockerfile                          # Python 3.12-slim, uvicorn on port 8000
├── requirements.txt                    # 21 Python dependencies
├── pytest.ini                          # pytest config with deprecation filter warnings
├── alembic.ini                         # Alembic DB migration config
├── .env.example                        # Environment variable template
│
├── app/
│   ├── __init__.py
│   ├── config.py                       # Side-effect: loads .env via python-dotenv
│   ├── main.py                         # FastAPI application + POST /analyze endpoint (177 lines)
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py               # SQLAlchemy engine factory (SSH tunnel for local, direct for prod)
│   │   └── models.py                   # Document ORM model with pgvector Vector(1024)
│   │
│   ├── ingestion/
│   │   ├── __init__.py
│   │   └── metadata_helpers.py         # Pure functions: frontmatter parsing, rank/status/ELI extraction
│   │
│   └── retrieval/
│       ├── __init__.py                 # Package docstring
│       ├── embedder.py                 # [MIGRATION TARGET] Cohere embedding client (135 lines)
│       ├── key_pool.py                 # [MIGRATION TARGET] API key rotation pool (401 lines)
│       ├── searcher.py                 # pgvector + tsvector search (96 lines)
│       ├── fusion.py                   # Reciprocal Rank Fusion (54 lines)
│       ├── context_builder.py          # LLM prompt context formatter (75 lines)
│       └── llm.py                      # Groq LangChain analysis (156 lines)
│
├── scripts/
│   ├── .gitkeep
│   └── ingest.py                       # [MIGRATION TARGET] Ingestion pipeline CLI (550 lines)
│
├── alembic/
│   ├── env.py                          # Alembic environment setup
│   ├── script.py.mako                  # Migration script template
│   └── versions/
│       ├── 0001_initial.py             # Initial schema: documents, pgvector, ivfflat index
│       ├── 0002_fix_ivfflat_lists.py   # Fix ivfflat index with lists=50
│       └── 0003_metadata_refactor.py   # Add status/legal_rank/jurisdiction/source_metadata columns
│
└── tests/
    ├── __init__.py
    ├── conftest.py                     # pytest fixtures (rate limit + API key defaults)
    ├── test_main_auth.py               # Auth tests for POST /analyze
    ├── test_retrieval.py               # Tests for retrieval modules (345 lines)
    ├── test_ingestion.py              # Tests for ingestion pipeline (659 lines)
    ├── test_db.py                      # Tests for DB operations
    ├── ingestion/
    │   ├── __init__.py
    │   └── test_metadata_helpers.py    # Tests for pure-function metadata helpers (253 lines)
    └── retrieval/
        ├── __init__.py
        └── test_key_pool.py            # Tests for KeyPool (763 lines)
```

## Module Roles

### Core Application (`app/`)

| Module | Role | Lines | Key Classes/Functions |
|--------|------|-------|----------------------|
| `app/main.py` | FastAPI entry point, routing, request handling | 177 | `POST /analyze`, `GET /health`, lifespan |
| `app/config.py` | Load .env into process env | 4 | `load_dotenv()` |
| `app/db/connection.py` | SQLAlchemy engine factory | 95 | `get_engine()` |
| `app/db/models.py` | ORM model definitions | 46 | `Document` (Vector, JSONB, TSVECTOR) |
| `app/ingestion/metadata_helpers.py` | Pure functions for legal metadata | 271 | `parse_frontmatter`, `extract_legal_rank`, `normalize_status`, `derive_eli` |

### Retrieval Modules (`app/retrieval/`)

| Module | Role | Lines | Migration Impact |
|--------|------|-------|-----------------|
| `embedder.py` | Query-time Cohere embedding client | 135 | **HIGH** — Entire Cohere client replaced with Ollama HTTP call |
| `key_pool.py` | Provider-agnostic API key rotation | 401 | **HIGH** — Can be removed/simplified for Ollama (no API keys) |
| `searcher.py` | Vector + BM25 search | 96 | NONE — No change needed if dimension stays 1024 |
| `fusion.py` | RRF merge | 54 | NONE — No embedding dependency |
| `context_builder.py` | Prompt formatting | 75 | NONE — No embedding dependency |
| `llm.py` | Groq LLM analysis | 156 | NONE — Separate API (not part of migration) |

### Ingestion (`scripts/`)

| Module | Role | Lines | Migration Impact |
|--------|------|-------|-----------------|
| `ingest.py` | Standalone CLI ingestion pipeline | 550 | **HIGH** — `generate_embeddings()` uses Cohere directly |

### Tests

| Module | Role | Lines | Migration Impact |
|--------|------|-------|-----------------|
| `tests/test_retrieval.py` | Tests for retrieval pipeline | 345 | **MEDIUM** — embedder tests mock Cohere |
| `tests/test_ingestion.py` | Tests for ingest pipeline | 659 | **MEDIUM** — generate_embeddings tests mock Cohere |
| `tests/retrieval/test_key_pool.py` | KeyPool tests | 763 | **HIGH** — May be removed if KeyPool is eliminated |
| `tests/ingestion/test_metadata_helpers.py` | Metadata helper tests | 253 | NONE — Pure functions, no Cohere dependency |

## Build and Test Conventions

| Convention | Value |
|-----------|-------|
| Runtime | Python 3.12 |
| ASGI Server | uvicorn |
| Test Framework | pytest 8.x |
| Test Mocking | unittest.mock (MagicMock) |
| DB Migrations | Alembic |
| DB Driver | psycopg2-binary |
| Dependency File | `requirements.txt` (flat, no pyproject.toml) |
| Container | Docker (python:3.12-slim) |
| Entrypoint | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |

### Test Patterns
- All tests are fully mocked — no network or database access
- Tests import the module under test directly with `sys.path.insert(0, ...)` for import isolation
- `conftest.py` sets env defaults for `ANALYZE_RATE_LIMIT` and `API_KEY`
- KeyPool tests use a `setup_method` that resets embedder/llm module-level singletons

### CI Commands
```bash
# Run tests
cd thermia-back && python -m pytest tests/

# Run app
cd thermia-back && uvicorn app.main:app --reload

# Run ingestion
cd thermia-back && python scripts/ingest.py

# Run migration
cd thermia-back && alembic upgrade head
```
