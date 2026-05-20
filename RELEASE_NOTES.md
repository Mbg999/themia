# Release Notes

## 0.3.0 (2026-05-20)

### Added

- **Ollama BGE-M3 embedding backend**: `thermia-back/app/retrieval/embedder.py` is now a
  singleton that calls the self-hosted Ollama endpoint
  (`https://ollama.cvbooster.es/api/embeddings`, model `bge-m3`). The 1024-dimension
  interface is preserved; no callers needed changes.
- **`_validate_host()` SSRF guard**: the Ollama host is validated at module load and at
  FastAPI startup (lifespan hook). Non-localhost hosts must use `https://`; bare `http://`
  to external addresses is rejected (CWE-918).
- **30-second client timeout**: `ollama.Client` is initialised with `timeout=30.0` to
  prevent unbounded blocking on a slow or unresponsive Ollama node (CWE-400 / DoS
  hardening).
- **Double-checked locking singleton**: the `EmbedderClient` class uses a module-level
  `_lock` and a double-check pattern so concurrent startup requests cannot race to create
  two clients.
- **Startup validation in FastAPI lifespan**: `_validate_host()` is called inside
  `app/main.py` lifespan so the server refuses to start with an invalid `OLLAMA_HOST`
  value rather than failing at first embed call.

### Changed

- **`KeyPool` stripped of Cohere-specific logic** (`app/retrieval/key_pool.py`): all
  Cohere API-key rotation, per-key rate-limit tracking, and fallback logic removed. The
  class now holds general-purpose API keys without vendor assumptions.
- **Ingestion pipeline** (`scripts/ingest.py`): `generate_embeddings()` now calls
  `ollama.Client.embeddings()` directly. Cohere batch API calls and credential management
  removed.
- **Exception logging sanitised**: caught exceptions in the embedder no longer log the
  raw Ollama URL, preventing host/path leakage in log aggregators.
- **`OLLAMA_HOST` env var** replaces `COHERE_API_KEYS` as the primary embedding
  configuration variable. `OLLAMA_MODEL` (default `bge-m3`) controls the model name.

### Fixed

- `raise last_exc` guard added to the embedder retry loop so a retry exhaustion that
  set no exception cannot silently swallow failures.
- Embedding dimension mismatch detection: the embedder validates the returned vector
  length against `EMBEDDING_DIM` and raises `ValueError` immediately rather than
  propagating a wrong-sized vector into pgvector.

### Deprecated

- **Cohere `embed-multilingual-v3.0` integration** is fully replaced and will not be
  restored. `COHERE_API_KEYS` env var is no longer read by the application. Remove it
  from all deployment environments by **2026-08-20**.
- **Re-ingestion required**: documents already stored in pgvector were embedded with the
  Cohere model. Those embeddings are incompatible with BGE-M3 vectors. A full
  re-ingestion pass is required before semantic search produces correct results
  (see migration plan at `aidlc-docs/operations/2026-05-20t08-41-48z-bge-m3-migration-migration-plan.md`).

### Security

- **CWE-918 (SSRF)**: `_validate_host()` in `embedder.py` enforces `https://` for
  non-localhost `OLLAMA_HOST` values, blocking SSRF via a crafted host pointing to
  internal infrastructure.
- **CWE-918 (SSRF in ingestion)**: same host-validation logic applied to `ingest.py`
  to prevent the ingestion CLI from being used as an SSRF vector.
- **CWE-400 (DoS via unbounded HTTP)**: 30-second timeout on the Ollama client prevents
  slow-loris style denial-of-service against the embedding service.

---

## 0.2.0 (2026-05-20)

### Added

- **Two-layer metadata architecture**: every ingested document now carries a curated
  `metadata_` JSONB column (law_id, article, section, hierarchy_path, eli, status,
  legal_rank, jurisdiction, content_hash) alongside a raw `source_metadata_` JSONB
  column that preserves the original YAML frontmatter verbatim. Downstream retrieval
  queries run against the curated layer while provenance is never lost.
- **`metadata_helpers` module** (`thermia-back/app/ingestion/metadata_helpers.py`):
  `parse_frontmatter`, `derive_eli`, `extract_legal_rank`, `normalize_status`,
  `compute_content_hash`, and `build_metadata_payload` — all independently unit-tested.
- **Alembic migration 0003**: adds four new columns (`status`, `legal_rank`,
  `jurisdiction`, `source_metadata_`) and four PostgreSQL indexes to the `documents`
  table. Indexes are created with `CONCURRENTLY` to avoid exclusive locks on live tables.
- **`only_active` filter** in `vector_search` and `bm25_search`: filters results to
  documents whose status is in `['vigente', 'parcialmente vigente', '']`, allowing
  partially-in-force laws to appear in results.
- **Enriched `/analyze` sources response**: the `fuentes` array now returns nine fields
  per source (previously three): `titulo`, `articulo`, `seccion`, `ley_id`, `eli`,
  `status`, `legal_rank`, `jurisdiction`, `hierarchy_path`.
- **Angular sources-display component**: legal rank, status, and jurisdiction badges in
  `app.html`/`app.scss`; colour-coded by status value.
- **GitHub Actions CI workflow** (draft): `ci.yml` covering `pytest` and
  `alembic check` on every push/PR to `main`.

### Changed

- **Ingestion pipeline** (`scripts/ingest.py`): wired to populate all new metadata
  columns; `extract_legal_rank` now defers to the parsed H1 law title when frontmatter
  `rank` is absent.
- **FastAPI lifespan** (`app/main.py`): SSH tunnel and database engine are now created
  once at startup and torn down at shutdown via `@asynccontextmanager lifespan`,
  eliminating per-request tunnel teardown.
- **`asyncio.get_event_loop()`** replaced with `asyncio.to_thread()` throughout
  `app/main.py` for Python 3.10+ compatibility.
- **`app/retrieval/context_builder.py`**: document chunks are now wrapped in
  `<doc id="N">...</doc>` XML delimiters before LLM concatenation.
- `AnalysisService` in Angular frontend updated to consume the new nine-field source
  shape; `Fuente` interface extended accordingly.

### Fixed

- `only_active` filter previously excluded `'parcialmente vigente'` documents — now
  correctly included.
- Alembic upgrade function now uses `ADD COLUMN IF NOT EXISTS` and
  `CREATE INDEX IF NOT EXISTS` for idempotent re-runs.
- `server_default=text('{}')` used for JSONB columns to avoid SQLAlchemy dialect
  string-literal vs. SQL-expression ambiguity.
- `upsert_documents` now guards against writing a NULL embedding when
  `chunk['embedding']` is None.

### Deprecated

- Direct use of the three-field `fuentes` shape (`titulo`, `articulo`, `seccion`)
  is deprecated. Callers should migrate to the nine-field shape by **2026-08-20**.
  The legacy shape is not removed in this release but will be removed in 0.3.0.

### Security

- **CWE-77 (Prompt Injection)**: document content is now wrapped in `<doc>...</doc>`
  XML delimiters in `context_builder.py` with an explicit system instruction that
  the LLM must treat delimited content as data, not instructions.
- **CWE-400 (YAML Bomb / Billion-Laughs DoS)**: `parse_frontmatter` now enforces a
  64 KB size gate before calling `yaml.safe_load`.
- **CWE-601 (Open Redirect / URL Scheme injection)**: `derive_eli` now validates that
  ELI values begin with `https://`, `http://`, or a relative `eli/` path; all other
  schemes (including `javascript:`) are rejected and return `None`.
- **CWE-601 (API boundary)**: the `/analyze` response serialiser now validates each
  `eli` value against the same allowlist before including it in the `fuentes` payload.
