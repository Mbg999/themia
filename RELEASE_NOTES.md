# Release Notes

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
