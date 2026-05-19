# Unit Spec: `ingestion-wiring`
**Run:** `2026-05-19t20-50-00z-metadata-refactor`
**Layer:** 1 (depends on: `db-schema-refactor`, `metadata-helpers`)

## Purpose
Wire the new metadata architecture into the existing ingestion pipeline (`scripts/ingest.py`). This unit integrates frontmatter parsing, two-layer metadata construction, content hashing with active embed-skip, and extended `upsert_documents()` to populate the new DB columns.

## Responsibilities
- Call `parse_frontmatter()` inside `parse_legal_structure()` to extract frontmatter before Markdown parsing
- Build retrieval metadata (16 fields, FR-2.1) and source metadata (remaining frontmatter fields) per chunk
- Implement active hash-skip: query `content_hash` before embed; skip Cohere call on match
- Update `upsert_documents()` to write `source_metadata`, `status`, `legal_rank`, `jurisdiction` columns
- Guard against NULL embedding overwrite when hash-skip fires
- Add `PyYAML>=6.0` to `requirements.txt` if not already present
- Extend `tests/test_ingestion.py` with hash-skip and new column tests

## Public Interfaces
- **`parse_legal_structure(md_text, *, source_file, jurisdiction) -> list[dict]`** — now returns chunks with three keys: `content`, `metadata` (retrieval), `source_metadata`
- **`upsert_documents(session_maker, chunks) -> None`** — now writes 4 additional DB columns per document

## Internal Dependencies
- **`db-schema-refactor`** — `Document` model must have `status`, `legal_rank`, `jurisdiction`, `source_metadata_` attributes before this unit writes to them
- **`metadata-helpers`** — imports `parse_frontmatter`, `compute_content_hash`, `extract_legal_rank`, `normalize_status`, `derive_eli` from `app.ingestion.metadata_helpers`

## External Dependencies
- `cohere` — existing (Cohere embed API)
- `sqlalchemy` — existing (ORM session, `select`, `func`)
- `PyYAML>=6.0` — new (via `metadata-helpers`; ensure in `requirements.txt`)

## Tasks
| Task | Description |
|---|---|
| IW-T1 | Add `_RETRIEVAL_FIELDS` set + `build_source_metadata()` + update `chunk_article()` to produce two-layer metadata |
| IW-T2 | Call `parse_frontmatter` inside `parse_legal_structure`; pass frontmatter to `chunk_article` |
| IW-T3 | Implement hash-skip: `SELECT content_hash WHERE id=?` before embed; sentinel `None` if match |
| IW-T4 | Update `upsert_documents()`: write `source_metadata_`, `status`, `legal_rank`, `jurisdiction`; guard `embedding=None` |
| IW-T5 | Add `PyYAML>=6.0` to `requirements.txt` if absent |
| IW-T6 | Extend `tests/test_ingestion.py` with `TestHashSkip`, `TestUpsertSourceMetadata`, `TestUpsertRealColumns` |

## Critical Constraint — Hash-skip Embedding Guard (Risk 1)
When `content_hash` matches (hash-skip), `chunk["embedding"]` is set to `None`. `upsert_documents()` **must not** pass `embedding=None` to `Document(...)` — pgvector would overwrite the stored 1024-dimensional vector with NULL. Implementation must fetch the existing embedding from DB before merge, or conditionally set `doc.embedding` only when not None.

## Acceptance Criteria
- `chunk_article(text, ..., frontmatter={"rank": "ley", "status": "in_force", "dept": "Min"})`:
  - `chunk["metadata"]["legal_rank"] == "ley"`
  - `chunk["metadata"]["status"] == "vigente"`
  - `chunk["metadata"]["content_hash"]` is 64-char hex
  - `chunk["source_metadata"]["dept"] == "Min"`, does NOT contain `legal_rank`
- `parse_legal_structure` on BOE-A-1835-2348: `chunk["content"]` contains no `---` frontmatter text
- Re-run on unchanged corpus: `generate_embeddings` called zero times
- Re-run on 1 changed article: `generate_embeddings` called exactly once
- After upsert: `SELECT source_metadata FROM documents WHERE id=?` → non-empty JSON
- After upsert: `SELECT status, legal_rank, jurisdiction FROM documents WHERE id=?` → normalized values
- `pytest tests/test_ingestion.py -v` → all tests pass (including new ones), no DB/Cohere connection

## Definition of Done
- [ ] `scripts/ingest.py` updated: `_RETRIEVAL_FIELDS`, `build_source_metadata`, `chunk_article`, `parse_legal_structure`, hash-skip SELECT, `upsert_documents`
- [ ] `requirements.txt` contains `PyYAML>=6.0`
- [ ] `tests/test_ingestion.py` extended with ≥6 new test cases
- [ ] All existing tests still pass
- [ ] Hash-skip guard verified: no NULL embedding overwrites
