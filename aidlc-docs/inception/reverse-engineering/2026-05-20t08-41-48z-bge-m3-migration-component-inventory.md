# Component Inventory — Thermia

## Core Components

### 1. Embedder (`app/retrieval/embedder.py`)
**Responsibility**: Generate 1024-d query embeddings via Cohere API.
**Migration Target**: Replace Cohere `embed-multilingual-v3.0` with Ollama `bge-m3`.

| Aspect | Detail |
|--------|--------|
| **Entry Points** | `get_query_embedding(text)`, `get_cohere_pool()`, `_get_client()` |
| **Dependencies** | `cohere` package, `app.retrieval.key_pool` (KeyPool, AllKeysExhaustedError, classify_failure) |
| **State** | Module-level singletons: `_cohere_client`, `_cohere_client_key`, `_cohere_pool` |
| **Model** | `embed-multilingual-v3.0`, 1024 dimensions |
| **Input Type** | `search_query` (query-time embedding) |
| **Retry Strategy** | 3 delays (10s, 30s, 60s) for 429s, then pool rotation |
| **Error Handling** | 429s → retry + rotate; 400/401/403 → re-raise immediately |
| **Thread Safety** | Pool uses `threading.Lock`; client rebuilt atomically on key change |
| **Tests** | `test_retrieval.py` → `TestEmbedderKeyPool` (3 tests) |

### 2. KeyPool (`app/retrieval/key_pool.py`)
**Responsibility**: Provider-agnostic API key rotation with cool-down, used by both Cohere and Groq.
**Migration Impact**: Can be simplified or removed for Ollama (no API keys needed for self-hosted).

| Aspect | Detail |
|--------|--------|
| **Entry Points** | `KeyPool.from_env()`, `KeyPool.current()`, `KeyPool.mark_failed()`, `classify_failure()` |
| **Providers** | `"cohere"`, `"groq"` |
| **Key Loading** | JSON array (`COHERE_API_KEYS`/`GROQ_API_KEYS`) or legacy scalar (`COHERE_API_KEY`/`GROQ_API_KEY`) |
| **Cooldowns** | Cohere: 30 days (trial key reset), Groq: 1 day (daily quota) |
| **Failure Signals** | RateLimit (429), CohereTrialQuota, GroqDailyQuota, Persistent5xx |
| **Thread Safety** | `threading.Lock` on all mutations |
| **Logging** | Structured logs with key hashes (never raw keys), transition-once flags |
| **Tests** | `test_key_pool.py` → `TestKeyPoolSkeleton`, `TestFromEnv`, `TestClassifyFailure`, `TestKeyPoolRotation`, `TestNoRawKeysInLogs` (42 tests total) |

### 3. Ingest Pipeline (`scripts/ingest.py`)
**Responsibility**: CLI script that ingests Spanish legal documents into the vector database.
**Migration Target**: Replace Cohere call in `generate_embeddings()` with Ollama.

| Aspect | Detail |
|--------|--------|
| **Source** | `https://github.com/legalize-dev/legalize-es` (pinned to commit `2ffdecd`) |
| **Parsing** | H1=Law, H2=Section, H3+=Article; YAML frontmatter extraction |
| **Chunking** | ≤800 tokens → single chunk; >800 → sub-chunks of ≤512 tokens with 50-token overlap |
| **Embedding** | `cohere.Client(pool.current()).embed()` with `input_type="search_document"`, batch size 50 |
| **Rate-Limiting** | 3 retry delays (10s, 30s, 60s), 1s inter-batch sleep, pool rotation on 429 |
| **DB Write** | upsert via `session.merge()` with deterministic UUID5 from `(source_file, article)` |
| **Key Functions** | `parse_legal_structure()`, `chunk_article()`, `build_embedding_text()`, `generate_embeddings()`, `upsert_documents()` |
| **Tests** | `test_ingestion.py` → 6 test classes (50+ tests) |

### 4. Searcher (`app/retrieval/searcher.py`)
**Responsibility**: Hybrid search combining vector similarity and full-text search.

| Aspect | Detail |
|--------|--------|
| **Vector Search** | `vector_search()` → pgvector `<=>` cosine operator, `Vector(1024)`, ivfflat index |
| **Index Probes** | `SET LOCAL ivfflat.probes = 10` per query |
| **BM25 Search** | `bm25_search()` → PostgreSQL `tsvector @@ plainto_tsquery('spanish', ...)` |
| **Filters** | `status IN ("vigente", "parcialmente vigente", "")` for active-only queries |
| **Migration Impact** | None — no change needed if dimension stays 1024 |
| **Tests** | `test_retrieval.py` → `TestVectorSearch`, `TestBM25Search` (4 tests) |

### 5. Fusion (`app/retrieval/fusion.py`)
**Responsibility**: Combine vector and BM25 results via Reciprocal Rank Fusion.

| Aspect | Detail |
|--------|--------|
| **Formula** | `score(doc) = Σ 1/(60 + rank_i)` across all result lists |
| **Deduplication** | By `article` field in `metadata_` |
| **Top-N** | Configurable `top_n` (default 5) |
| **Migration Impact** | None — no embedding dependency |
| **Tests** | `test_retrieval.py` → `TestRRFFusion` (4 tests) |

### 6. Context Builder (`app/retrieval/context_builder.py`)
**Responsibility**: Format retrieved Document objects into a structured prompt string.

| Aspect | Detail |
|--------|--------|
| **Format** | `[law_id \| law_title]` + metadata line + `<doc>content</doc>` + `---` |
| **Migration Impact** | None |
| **Tests** | `test_retrieval.py` → `TestBuildContext` (3 tests) |

### 7. LLM Analyzer (`app/retrieval/llm.py`)
**Responsibility**: Analyze legal context via Groq llama-3.1-8b-instant.

| Aspect | Detail |
|--------|--------|
| **Provider** | Groq via LangChain `ChatGroq` |
| **Model** | `llama-3.1-8b-instant` (configurable via `GROQ_MODEL`) |
| **Key Pool** | Uses `KeyPool.from_env("groq")` singleton |
| **Output** | Structured JSON: `resumen`, `implicaciones_legales`, `fundamento_juridico` |
| **Migration Impact** | None — separate API from embeddings |
| **Tests** | `test_retrieval.py` → `TestLLMKeyPool` (4 tests) |

### 8. FastAPI App (`app/main.py`)
**Responsibility**: HTTP API entry point, authentication, request lifecycle.

| Aspect | Detail |
|--------|--------|
| **Endpoints** | `GET /health`, `POST /analyze` |
| **Rate Limiting** | slowapi, default 10/minute on `/analyze` |
| **Auth** | Bearer token via HMAC constant-time comparison |
| **CORS** | Configurable origins (default `http://localhost:4200`) |
| **Lifecycle** | Engine created on startup, tunnel stopped on shutdown |

### 9. Database Models (`app/db/models.py`)
**Responsibility**: SQLAlchemy ORM model for the `documents` table.

| Aspect | Detail |
|--------|--------|
| **Table** | `documents` |
| **Primary Key** | UUID (auto-generated via `gen_random_uuid()`) |
| **Vector Column** | `embedding vector(1024)` — the dimension that must stay 1024 |
| **Indexes** | ivfflat (embedding, cosine_ops, lists=50), GIN (tsvector, metadata) |
| **Other Columns** | content (TEXT), tsvector, metadata (JSONB), status, legal_rank, jurisdiction, source_metadata (JSONB) |

## Dependency Graph (Migration-Relevant)

```
scripts/ingest.py
    ├── cohere.Client(pool.current())        [MIGRATE to Ollama]
    ├── app.retrieval.embedder.get_cohere_pool()
    └── app.retrieval.key_pool.classify_failure

app/main.py
    ├── app.retrieval.embedder.get_query_embedding()   [MIGRATE to Ollama]
    ├── app.retrieval.searcher.vector_search()         [NO CHANGE]
    ├── app.retrieval.searcher.bm25_search()           [NO CHANGE]
    ├── app.retrieval.fusion.rrf_fusion()              [NO CHANGE]
    ├── app.retrieval.context_builder.build_context()  [NO CHANGE]
    └── app.retrieval.llm.analyze_with_llm()           [NO CHANGE]

app.retrieval.embedder
    ├── cohere.Client                                  [MIGRATE to Ollama]
    └── app.retrieval.key_pool                         [CAN REMOVE]

app.retrieval.llm
    ├── langchain_groq.ChatGroq                        [NO CHANGE]
    └── app.retrieval.key_pool                         [STAYS — Groq still needs key management]
```

## Component Count Summary

| Category | Count |
|----------|-------|
| Retrieval modules | 6 |
| Database modules | 2 |
| Ingestion modules | 1 (+ helpers) |
| App entry points | 1 |
| CLI scripts | 1 |
| Test files | 6 |
| Alembic migrations | 3 |
| Total Python files | 20 |
