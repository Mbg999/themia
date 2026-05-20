# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-05-20

### Added

- Ollama BGE-M3 self-hosted embedding backend (`embedder.py` singleton with
  `ollama.Client`, `OLLAMA_HOST` / `OLLAMA_MODEL` env vars).
- `_validate_host()` SSRF guard: non-localhost `OLLAMA_HOST` must use `https://`.
- 30-second client timeout on `ollama.Client` (DoS hardening, CWE-400).
- Double-checked locking singleton for thread-safe client initialisation.
- FastAPI lifespan calls `_validate_host()` at startup — server refuses to start with an
  invalid host.
- new `/analyze/text` endpoint: accepts raw text, returns analysis with embedded sources (no
  ingestion required).

### Changed

- `KeyPool` stripped of Cohere-specific key-rotation and rate-limit logic.
- `ingest.py` `generate_embeddings()` now uses `ollama.Client.embeddings()` directly.
- Exception logging in embedder sanitised — raw Ollama URL no longer logged.
- `OLLAMA_HOST` / `OLLAMA_MODEL` env vars replace `COHERE_API_KEYS`.
- `cohere` package removed from `requirements.txt`; `ollama` added and pinned.

### Fixed

- `raise last_exc` guard added to embedder retry loop (silent failure on exhaustion).
- Embedding dimension validation: returned vector length checked against `EMBEDDING_DIM`
  before insertion into pgvector.

### Deprecated

- Cohere `embed-multilingual-v3.0` integration fully replaced. `COHERE_API_KEYS` env var
  no longer read. Remove from all deployment environments by **2026-08-20**.
- Existing pgvector embeddings (Cohere-generated) are incompatible with BGE-M3 vectors;
  full re-ingestion required (see migration plan).

### Security

- CWE-918 (SSRF): `_validate_host()` in `embedder.py` and `ingest.py` blocks HTTP to
  non-localhost Ollama hosts.
- CWE-400 (DoS): 30-second timeout prevents unbounded blocking on a slow Ollama node.

## [0.2.0] - 2026-05-20

### Added

- Two-layer metadata architecture: curated `metadata_` JSONB (law_id, article, section,
  hierarchy_path, eli, status, legal_rank, jurisdiction, content_hash) plus raw
  `source_metadata_` JSONB for original frontmatter provenance.
- `metadata_helpers` module with `parse_frontmatter`, `derive_eli`, `extract_legal_rank`,
  `normalize_status`, `compute_content_hash`, and `build_metadata_payload`.
- Alembic migration 0003: four new columns and four concurrent indexes on `documents`.
- `only_active` filter in `vector_search` / `bm25_search` accepting
  `['vigente', 'parcialmente vigente', '']`.
- Enriched `/analyze` sources response: `fuentes` now returns nine fields per source.
- Angular sources-display: legal rank, status, jurisdiction badges with colour coding.
- Draft GitHub Actions CI workflow (`ci.yml`): pytest + alembic check.

### Changed

- Ingestion pipeline wired to populate all new metadata columns.
- FastAPI SSH tunnel and DB engine moved to lifespan (startup/shutdown) instead of
  per-request creation/teardown.
- `asyncio.get_event_loop()` replaced with `asyncio.to_thread()` for Python 3.10+.
- Document chunks wrapped in `<doc id="N">...</doc>` XML delimiters before LLM context.
- `AnalysisService` and `Fuente` interface updated to nine-field source shape.

### Fixed

- `only_active` filter previously silently excluded `'parcialmente vigente'` documents.
- Alembic upgrade now uses `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`
  for idempotent re-runs.
- `server_default=text('{}')` for JSONB columns (SQLAlchemy expression, not string).
- `upsert_documents` now guards against NULL embedding writes when embedding is None.

### Deprecated

- Three-field `fuentes` shape (`titulo`, `articulo`, `seccion`) — migrate to nine-field
  shape by **2026-08-20**. Will be removed in 0.3.0.

### Security

- Prompt injection mitigation: `<doc>` XML delimiters in `context_builder.py` (CWE-77).
- 64 KB YAML frontmatter size gate before `yaml.safe_load` (CWE-400).
- ELI URL scheme allowlist in `derive_eli` — blocks `javascript:` and similar (CWE-601).
- Server-side ELI allowlist validation in `/analyze` response serialiser (CWE-601).

## [0.1.0] - 2026-05-19

### Added

- Initial MVP: FastAPI backend with pgvector hybrid search (vector + BM25 + RRF fusion).
- Cohere embeddings with API key pool and per-key rate-limit fallback.
- SSH tunnel lifecycle for remote PostgreSQL access.
- Angular frontend with query input and sources display.
- Basic ingestion pipeline for Spanish legal Markdown corpus.

[Unreleased]: https://github.com/Mbg999/themia/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Mbg999/themia/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Mbg999/themia/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Mbg999/themia/releases/tag/v0.1.0
