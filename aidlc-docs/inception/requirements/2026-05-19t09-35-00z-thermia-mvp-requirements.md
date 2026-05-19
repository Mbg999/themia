# Thermia — Requirements Specification
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp
**Date:** 2026-05-19
**Status:** Approved (Pass 2)
**Depth:** Comprehensive

---

## 1. Intent Analysis

| Axis | Value |
|---|---|
| Clarity | Clear |
| Type | New Project |
| Scope | System-wide (full-stack, two pipelines) |
| Complexity | Complex |

**Purpose:** Build Thermia, an MVP application that ingests Spanish legal documents from the [legalize-es](https://github.com/legalize-dev/legalize-es) GitHub corpus, stores them in a hybrid vector + full-text search database, and exposes an endpoint that accepts a user-uploaded PDF, retrieves relevant legal context via RRF-fused search, and generates a structured Spanish-language analysis (summary, legal implications, citations) using a Groq-hosted LLM.

**Target user:** Non-expert users who need to understand how existing Spanish law applies to a document they have, without legal training.

---

## 2. System Overview

Thermia is a monorepo with two services:

| Service | Location | Technology |
|---|---|---|
| Backend | `thermia-back/` | FastAPI, LangChain, SQLAlchemy, PostgreSQL + pgvector |
| Frontend | `thermia-front/` | Angular 21.2.0, SCSS (per DESIGN.md) |

**Deployment model:**
- Local development: apps run natively (or via Docker); PostgreSQL runs on a remote VPS, accessed via `sshtunnel`.
- Production: `thermia-back` + `thermia-front` deployed to the same VPS via Docker Compose (`thermia-back` + `thermia-front`/nginx). PostgreSQL is a VPS-local service — accessed directly.

---

## 3. Functional Requirements

### 3.1 Ingestion Pipeline (`thermia-back/scripts/ingest.py`)

A manually-executable Python script that populates the database from the legalize-es corpus.

| # | Requirement | Notes |
|---|---|---|
| ING-1 | Clone `https://github.com/legalize-dev/legalize-es` into a temp directory | Use `gitpython` or `subprocess git clone` |
| ING-2 | Scan all `.md` files in the cloned repo | Recursive walk |
| ING-3 | Parse legal hierarchy: `law → title → article` from Markdown heading structure | H1 = law, H2 = title, H3+ = article |
| ING-4 | Create one chunk per legal article, preserving hierarchy | `chunk_type: "article"` |
| ING-5 | Sub-chunk articles exceeding **800 tokens** (overlap: 50 tokens) | Each sub-chunk must be ≤ **512 tokens** to fit Cohere embed-multilingual-v3.0's context window; `chunk_type: "sub_article"` |
| ING-6 | Prefix every chunk text for embedding with `[LAW X - ARTICLE Y - TITLE Z]\n\narticle text...` | Exact format |
| ING-7 | Attach enriched metadata to every chunk (see §3.3) | JSONB column |
| ING-8 | Generate embeddings via **Cohere `embed-multilingual-v3.0`** (1024d, cosine) | API key from `COHERE_API_KEY` env var |
| ING-9 | Store chunks in the `documents` table using **upsert** keyed on `(source_file, article)` | Idempotent re-runs — existing rows for the same article are replaced |
| ING-10 | Populate `tsvector` column for BM25/full-text search (Spanish tokenization) | `to_tsvector('spanish', content)` |
| ING-11 | Print progress to stdout: files processed, chunks written, errors | Suitable for manual execution |
| ING-12 | Accept a `--reset` flag that truncates the `documents` table before running | Enables full re-ingest when needed |

**Chunk metadata schema:**
```json
{
  "law_id": "string",
  "law_title": "string",
  "article": "string",
  "section": "string",
  "chunk_type": "article | sub_article",
  "source_file": "string (relative path in repo)",
  "jurisdiction": "ES",
  "year": 0,
  "hierarchy_path": "string (e.g. 'Ley Orgánica / Título I / Artículo 1')"
}
```

### 3.2 Retrieval Pipeline (`POST /analyze`)

FastAPI endpoint that accepts a PDF file, extracts its text, queries the vector+BM25 database, builds context, calls the LLM, and returns a structured Spanish analysis.

| # | Requirement | Notes |
|---|---|---|
| RET-1 | Accept `multipart/form-data` with a single `.pdf` file field | Validated: must be `.pdf` MIME type |
| RET-2 | Extract text from the PDF using **`pdfplumber`** | |
| RET-3 | Guard: if extracted text is empty OR text does not appear related to legal content → return `HTTP 422` with Spanish message (see §3.5) | Simple heuristic: check for legal keywords (`artículo`, `ley`, `decreto`, `contrato`, `obligación`, etc.) |
| RET-4 | Intent detection — simple MVP heuristic: identify if query targets a specific law, article, or general topic | Influences metadata filter |
| RET-5 | Apply metadata filter: `jurisdiction = "ES"` always; add `law_id` filter if intent detection identified a specific law | |
| RET-6 | Vector search via **pgvector cosine similarity** on the `embedding` column: retrieve top-20 candidates | Cohere embedding of the PDF text used as query vector |
| RET-7 | BM25 search via **PostgreSQL `tsvector`** (`ts_rank_cd`): retrieve top-20 candidates | `to_tsquery('spanish', ...)` on `content` |
| RET-8 | Merge vector and BM25 results using **Reciprocal Rank Fusion (RRF)**: `score = Σ 1/(k + rank_i)` with `k=60` | Do NOT sum raw scores; use rank positions only |
| RET-9 | Deduplicate results by `article_id` (same `(source_file, article)` pair) | Keep highest-scored occurrence |
| RET-10 | Select top-5 chunks after deduplication | Configurable via env var `THERMIA_TOP_K` (default: 5) |
| RET-11 | Build context string in mandatory format (see §3.4) | |
| RET-12 | Call **Groq `llama-3.1-8b-instant`** via LangChain with Spanish prompt | API key from `GROQ_API_KEY` env var |
| RET-13 | LLM must return structured output with 3 sections: `resumen`, `implicaciones_legales`, `fundamento_juridico` | Use LangChain structured output / pydantic schema |
| RET-14 | Return response in the nested JSON schema (see §3.5) | |
| RET-15 | On any LLM API error (rate limit, timeout, quota): return `HTTP 503` with Spanish error body | No retry; see §3.5 |
| RET-16 | Authenticate requests with `Authorization: Bearer <key>` header | Key from `THERMIA_API_KEY` env var; `HTTP 401` if missing/wrong |

### 3.3 Database Schema

Single table `documents` managed via **SQLAlchemy + Alembic migrations**.

```sql
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT NOT NULL,
    embedding   VECTOR(1024),          -- Cohere embed-multilingual-v3.0
    tsvector    TSVECTOR,              -- populated via trigger or ingest script
    metadata    JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON documents USING GIN (tsvector);
CREATE INDEX ON documents USING GIN (metadata jsonb_path_ops);
```

> **Note:** `pgvector` extension must be enabled: `CREATE EXTENSION IF NOT EXISTS vector;`

### 3.4 Context Builder Format

The context string passed to the LLM must use this exact format for each chunk:

```
[{law_title} | Artículo {article} | {section}]

{content}

---
```

Chunks are concatenated in RRF rank order, separated by `---`.

### 3.5 API Response and Error Schemas

**Success response (`HTTP 200`):**
```json
{
  "analysis": {
    "resumen": "string (plain Spanish summary for non-experts)",
    "implicaciones_legales": ["string", "..."],
    "fundamento_juridico": ["string (exact citation e.g. 'Art. 3.1 LO 3/2018')", "..."]
  },
  "metadata": {
    "chunks_used": 5,
    "processing_time_ms": 1200
  }
}
```

**Out-of-scope guard (`HTTP 422`):**
```json
{
  "error": "El documento proporcionado no parece contener contenido jurídico o está vacío. Thermia solo puede analizar documentos legales en español."
}
```

**LLM unavailable (`HTTP 503`):**
```json
{
  "error": "El servicio de análisis no está disponible temporalmente. Por favor, inténtelo de nuevo más tarde."
}
```

**Unauthorized (`HTTP 401`):**
```json
{
  "error": "API key requerida. Incluya el header Authorization: Bearer <key>."
}
```

### 3.6 Frontend (Angular — single view)

| # | Requirement |
|---|---|
| FE-1 | Single view at `/` — no routing needed |
| FE-2 | PDF file input — accepts `.pdf` only; show selected filename |
| FE-3 | "Analizar" button — disabled until a PDF is selected |
| FE-4 | Loading state while `POST /analyze` is in flight |
| FE-5 | Render `analysis.resumen` as a styled summary block |
| FE-6 | Render `analysis.implicaciones_legales` as a bulleted list |
| FE-7 | Render `analysis.fundamento_juridico` as a citation list |
| FE-8 | Display error messages (guard + LLM errors) in a styled error block |
| FE-9 | Apply DESIGN.md design system (colors, typography, spacing, components) |
| FE-10 | Include the API key in `Authorization: Bearer <key>` header; key from Angular environment variable |
| FE-11 | Backend URL configurable via Angular environment (`environment.ts`) |

---

## 4. Non-Functional Requirements

| # | Category | Requirement |
|---|---|---|
| NFR-1 | Language | All UI text and LLM output in Spanish only |
| NFR-2 | Correctness | Embedding dimension must be exactly 1024 (Cohere embed-multilingual-v3.0) |
| NFR-3 | Correctness | Sub-chunk size must be ≤ 512 tokens (Cohere context window) — not 800 |
| NFR-4 | Security | API key never logged; never exposed in frontend bundle source (use env injection) |
| NFR-5 | Observability | Backend logs: request ID, PDF size, chunks retrieved, LLM latency, total latency |
| NFR-6 | Simplicity | No microservices; single FastAPI app; no Celery/queues for MVP |
| NFR-7 | Portability | Docker Compose for production; SSH tunnel config for local dev |
| NFR-8 | Migrations | All DB schema changes via Alembic; no raw SQL outside migrations |
| NFR-9 | Configuration | All secrets and connection params via environment variables (no hardcoded values) |
| NFR-10 | Testing | Backend: Pytest unit tests for ingestion parsing + retrieval logic; Frontend: Vitest unit tests for Angular components |

---

## 5. Environment Variables

### Backend (`thermia-back/.env` — never committed)

| Variable | Description | Example |
|---|---|---|
| `GROQ_API_KEY` | Groq API key for LLM | `gsk_...` |
| `COHERE_API_KEY` | Cohere API key for embeddings | `...` |
| `THERMIA_API_KEY` | Bearer token for endpoint auth | `thermia-secret-key` |
| `DATABASE_URL` | SQLAlchemy DB URL (prod / Docker) | `postgresql+psycopg2://user:pass@localhost:5432/thermia` |
| `SSH_HOST` | SSH server hostname (local dev only) | `vps.example.com` |
| `SSH_USER` | SSH username (local dev only) | `deploy` |
| `SSH_KEY_PATH` | Path to SSH private key (local dev only) | `/home/user/.ssh/id_rsa` |
| `SSH_REMOTE_BIND_PORT` | Remote PostgreSQL port (local dev only) | `5432` |
| `THERMIA_TOP_K` | Number of chunks to pass to LLM (default: 5) | `5` |
| `THERMIA_ENV` | `local` or `production` — controls tunnel activation | `local` |

### Frontend (`thermia-front/src/environments/`)

| Variable | Description |
|---|---|
| `apiUrl` | Backend base URL (e.g. `http://localhost:8000`) |
| `apiKey` | Bearer token — same value as `THERMIA_API_KEY` |

---

## 6. Architecture Constraints

1. **Database topology:** PostgreSQL runs on a VPS for both environments. Local dev connects via `sshtunnel` (SSH tunnel wraps the DB connection). Production connects directly. The `THERMIA_ENV=local` flag activates the tunnel in the backend.
2. **No local PostgreSQL container:** Docker Compose does NOT include a `postgres` service. The DB is always remote.
3. **Docker Compose services (production):** `thermia-back` (FastAPI, port 8000) + `thermia-front` (nginx serving Angular build, port 80).
4. **Ingestion script:** runs outside Docker, directly on developer machine. Connects to VPS via SSH tunnel.
5. **No authentication beyond API key:** no user sessions, no JWT, no user management.
6. **MVP scope fence:** no admin UI, no document history, no multi-tenant, no streaming responses.

---

## 7. Ingestion–Embedding Tension Resolution

> **Resolved in requirements:** Cohere `embed-multilingual-v3.0` has a **512-token context window**. The user-specified sub-chunking threshold of 800 tokens triggers sub-chunking, but the resulting sub-chunks must themselves be ≤ 512 tokens to avoid silent truncation during embedding.
>
> **Decision:** The 800-token threshold controls *when* to sub-chunk an article. Sub-chunks are sized to target **450–512 tokens** with 50-token overlap. Articles ≤ 800 tokens are embedded as a single chunk; if that single chunk is between 512–800 tokens, it will be embedded with truncation — acceptable for MVP since legal articles in that range are edge cases and the key metadata is in the prefix.

---

## 8. User Scenarios

### 8.1 Happy path — analyze a rental contract
1. User uploads a `.pdf` rental contract
2. Frontend sends `POST /analyze` with Bearer token
3. Backend extracts text; detects legal keywords → passes guard
4. Intent: rental/housing law → filters for `ley_arrendamientos_urbanos`
5. RRF search returns top 5 relevant articles
6. LLM produces structured Spanish analysis
7. Frontend renders summary, implications, citations

### 8.2 Empty PDF
1. User uploads an empty or image-only PDF (no extractable text)
2. Backend detects empty text → returns 422 with guard message
3. Frontend displays styled error block

### 8.3 Non-legal document
1. User uploads a recipe PDF
2. Backend extracts text; no legal keywords found → returns 422
3. Frontend displays out-of-scope error

### 8.4 LLM unavailable
1. Groq rate limit hit during analysis
2. Backend returns 503 with Spanish message
3. Frontend displays "servicio no disponible" error

---

## 9. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-1 | Ingestion script processes all `.md` files from legalize-es and stores chunks; re-running produces the same row count (upsert is idempotent) |
| AC-2 | `POST /analyze` with a Spanish legal PDF returns HTTP 200 with all three `analysis` sections populated in Spanish |
| AC-3 | `POST /analyze` with an empty or non-legal PDF returns HTTP 422 with the Spanish guard message |
| AC-4 | `POST /analyze` without a valid Bearer token returns HTTP 401 |
| AC-5 | RRF fusion: result list contains no duplicate `(source_file, article)` pairs |
| AC-6 | Embedding dimension in `documents.embedding` is exactly 1024 |
| AC-7 | Sub-chunks are ≤ 512 tokens (enforced in ingest script) |
| AC-8 | Angular frontend renders all three analysis sections and handles error states |
| AC-9 | `docker compose up` starts both services; frontend loads at `localhost:80` |
| AC-10 | All secrets sourced from env vars; no hardcoded keys in any committed file |

---

## 10. Out of Scope (MVP)

- User authentication / accounts
- Document upload history / persistence
- Streaming LLM responses
- Multi-jurisdiction support (only ES)
- Admin dashboard
- Rate limiting on the API
- Automated ingestion (cron)
- Support for formats other than PDF
