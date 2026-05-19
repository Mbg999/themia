# Requirements: Metadata Refactor for Thermia Legal RAG
**Run:** `2026-05-19t20-50-00z-metadata-refactor`
**Date:** 2026-05-19
**Author:** requirements-analyst (inline, Pass 2)

---

## 1. Overview

Refactor the ingestion pipeline metadata architecture so Thermia's Spanish legal RAG system can:
- filter on legal status, rank, and jurisdiction efficiently
- avoid re-embedding unchanged article content on re-runs
- ground LLM responses in richer legal context (ELI, hierarchy, official dates)
- keep the ingestion pipeline readable and the data model simple

**Out of scope**: changes to the retrieval API (`searcher.py`, `fusion.py`, `context_builder.py`), the Angular frontend, and the LLM (`llm.py`). The new metadata fields are stored; retrieval-side consumption is a follow-on task.

---

## 2. Baseline (what exists today)

| Component | Current state |
|---|---|
| `documents` table | 5 columns: `id`, `content`, `embedding`, `tsvector`, `metadata JSONB` |
| `metadata` column | flat dict with 9 keys: `law_id`, `law_title`, `article`, `section`, `chunk_type`, `source_file`, `jurisdiction`, `year`, `hierarchy_path` |
| Alembic | 2 migrations: `0001_initial`, `0002_fix_ivfflat_lists` |
| `parse_legal_structure()` | reads raw Markdown; does **not** strip/parse YAML frontmatter |
| `chunk_article()` | produces flat metadata dict |
| `upsert_documents()` | idempotency via `uuid5(source_file\|article)` as primary key |
| Frontmatter | silently ignored; extracted fields not stored |

---

## 3. Functional Requirements

### FR-1 — YAML/Frontmatter Extraction

**FR-1.1** Add a `parse_frontmatter(md_text: str) -> tuple[dict, str]` function that:
- Detects a leading `---…---` block (first occurrence only)
- Parses the YAML inside it using `PyYAML` (`yaml.safe_load`)
- Returns `(frontmatter_dict, body_text)` where `body_text` has the frontmatter block removed
- On any parse error (malformed YAML, missing closing `---`): returns `({}, original_md_text)` and logs a WARNING

**FR-1.2** `parse_legal_structure()` must call `parse_frontmatter()` first and operate on `body_text`. Frontmatter content must never enter chunked article text or embeddings.

**FR-1.3** The parser must handle all three edge cases without raising:
- Missing frontmatter (no `---` block) → `frontmatter_dict = {}`
- Malformed YAML → `frontmatter_dict = {}` + WARNING log
- Frontmatter with unexpected field types (list where string expected) → field stored as-is or coerced to string

---

### FR-2 — Two-Layer Metadata Split

**FR-2.1 — Retrieval metadata** (stored in existing `metadata JSONB` column):

```python
{
    "law_id": str,          # BOE identifier, e.g. "BOE-A-1835-2348"
    "law_title": str,       # H1 heading text
    "article": str,         # H3+ heading text
    "section": str,         # H2 heading text (empty if none)
    "chunk_type": str,      # "article" | "sub_article"
    "source_file": str,     # relative path within legalize-es repo
    "jurisdiction": str,    # "ES" (default)
    "year": str,            # 4-digit year string or ""
    "hierarchy_path": str,  # "LAW_ID > Section > Article"
    "legal_rank": str,      # see FR-4; "" if not determinable
    "status": str,          # normalized Spanish value; see FR-5; "" if absent
    "eli": str | None,      # ELI URI if derivable; None otherwise
    "official_date": str,   # frontmatter publication_date as ISO date string; "" if absent
    "version_date": str,    # frontmatter last_updated as ISO date string; "" if absent
    "language": str,        # always "es"
    "content_hash": str,    # SHA256 hex of normalized article content; see FR-3
}
```

**FR-2.2 — Source metadata** (stored in new `source_metadata JSONB DEFAULT '{}'` column):

Informational-only fields extracted from frontmatter. Not used in retrieval filtering. Examples:
- `identifier`, `source`, `pdf_url`, `department`, `department_code`
- `rank_code`, `ambito_code`, `official_journal`, `journal_issue`
- `consolidation_status`, `scope`, `url_html_consolidada`
- `page_start`, `page_end`, `subjects`, `legislative_status`

All raw frontmatter fields that are **not** mapped to retrieval metadata go into `source_metadata`. Store them as-is (no normalization).

**FR-2.3** The split must be implemented in `chunk_article()` or a new `build_metadata()` helper — not scattered across multiple call sites.

---

### FR-3 — Content Hashing

**FR-3.1** Add a `compute_content_hash(text: str) -> str` function:
- Normalize: `text.strip().lower()` then collapse all whitespace runs to a single space
- Hash: `hashlib.sha256(normalized.encode("utf-8")).hexdigest()`
- Returns a 64-character lowercase hex string

**FR-3.2** `content_hash` is stored in retrieval metadata for every chunk (article and sub_article).

**FR-3.3 — Active skip on re-runs** (Q3=B): `upsert_documents()` must check the stored hash before calling Cohere embed:
- Query `SELECT metadata->>'content_hash' FROM documents WHERE id = <stable_uuid>` before generating the embedding
- If stored hash == new chunk's hash: skip the embed call entirely; still upsert the row (metadata may have changed)
- If stored hash differs or row doesn't exist: generate embedding and upsert normally
- The embed skip must be logged at DEBUG level: `[hash-match] skipped embed for <source_file> | <article>`

**FR-3.4** The hash is computed on the raw article text (before embedding-prefix construction). The same text that goes into `content` column is what gets hashed.

---

### FR-4 — Legal Rank Extraction

**FR-4.1** Add a `extract_legal_rank(frontmatter: dict, law_title: str) -> str` function.

Priority order:
1. `frontmatter.get("rank")` — present in legalize-es as e.g. `"orden"`, `"ley"`, `"real-decreto"`
2. Pattern-match against `law_title` (case-insensitive, Spanish):

| Pattern in title | `legal_rank` value |
|---|---|
| `constitución` | `constitucion` |
| `ley orgánica` | `ley_organica` |
| `ley` (not organic) | `ley` |
| `real decreto-ley` | `real_decreto_ley` |
| `real decreto` | `real_decreto` |
| `decreto` | `decreto` |
| `orden ministerial` | `orden_ministerial` |
| `orden` | `orden` |
| `resolución` | `resolucion` |
| `circular` | `circular` |
| `instrucción` | `instruccion` |

3. If neither source yields a match → return `""`

**FR-4.2** The `rank` frontmatter value must be normalized to the canonical snake_case values in the table above (e.g. `"real-decreto"` → `"real_decreto"`, `"orden"` → `"orden"`). Unknown raw rank values are stored as-is (lowercased, hyphens replaced with underscores).

---

### FR-5 — Legal Status Normalization

**FR-5.1** Add a `normalize_status(raw: str | None) -> str` function with this mapping:

| Frontmatter value | Normalized output |
|---|---|
| `"in_force"` | `"vigente"` |
| `"derogated"` | `"derogada"` |
| `"partially_in_force"` | `"parcialmente vigente"` |
| `None` or missing | `""` |
| Anything else | stored as-is (lowercased) + WARNING log |

**FR-5.2** The function must live in a small centralized helper module (`app/ingestion/metadata_helpers.py` or equivalent) — not inlined in the parser.

---

### FR-6 — ELI Derivation (conservative)

**FR-6.1** Add a `derive_eli(frontmatter: dict) -> str | None` function:
- Check `frontmatter.get("eli")` first (future-proof: if the field is added upstream)
- Otherwise attempt to extract from `frontmatter.get("source", "")` URL: if it contains `eli/` → extract the ELI path segment
- Otherwise return `None`
- Must never raise; on any parse error return `None`

**FR-6.2** `eli` is stored as `None` (Python `None` / SQL `NULL`) when not derivable — not as empty string. This is the only nullable field in retrieval metadata.

---

### FR-7 — Database Schema Changes

**FR-7.1 — Three new real columns** on `documents` table (Q2=A):

| Column | Type | Constraint | Index |
|---|---|---|---|
| `status` | `VARCHAR(32)` | `DEFAULT ''` | B-tree: `idx_documents_status` |
| `legal_rank` | `VARCHAR(64)` | `DEFAULT ''` | B-tree: `idx_documents_legal_rank` |
| `jurisdiction` | `VARCHAR(8)` | `DEFAULT 'ES'` | B-tree: `idx_documents_jurisdiction` |

**FR-7.2 — New `source_metadata` column** (Q1=A):
- `source_metadata JSONB DEFAULT '{}'`
- No index required at MVP

**FR-7.3 — Alembic migration `0003_metadata_refactor.py`**:
- `upgrade()`: `ALTER TABLE documents ADD COLUMN status VARCHAR(32) DEFAULT ''`, same for `legal_rank` and `jurisdiction`; `ADD COLUMN source_metadata JSONB DEFAULT '{}'`; create the 3 B-tree indexes
- `downgrade()`: `DROP INDEX …`, `DROP COLUMN …` for all 4 added columns
- Must be idempotent: use `IF NOT EXISTS` / `IF EXISTS` guards where possible

**FR-7.4 — SQLAlchemy model update** (`app/db/models.py`):
- Add `status`, `legal_rank`, `jurisdiction` as `Column(String(N), default="")` / `Column(String(8), default="ES")`
- Add `source_metadata_` as `Column("source_metadata", JSONB, server_default="{}")`
- Keep `metadata_` unchanged (column name `metadata` in DB)

**FR-7.5 — GIN index on `metadata` JSONB** for flexible filtering of retrieval fields not promoted to columns:
- `CREATE INDEX idx_documents_metadata_gin ON documents USING GIN (metadata jsonb_path_ops)`
- Added in migration `0003`

---

### FR-8 — Ingestion Pipeline Wiring

**FR-8.1** `ingest.py`'s `main()` loop must:
1. Read `md_text` from file
2. Call `parse_frontmatter(md_text)` → `(fm, body)`
3. Call `parse_legal_structure(body, source_file=rel_path)` → `chunks`
4. For each chunk, call `build_retrieval_metadata(fm, chunk_base)` and `build_source_metadata(fm)` to produce the two metadata dicts
5. Query existing hash (FR-3.3); skip embed if hash matches
6. Upsert with all new fields populated

**FR-8.2** `upsert_documents()` signature change: each chunk dict must carry `source_metadata` in addition to `content`, `embedding`, and `metadata`. The ORM write must populate `doc.source_metadata_` from `chunk["source_metadata"]`.

**FR-8.3** The three new real columns (`status`, `legal_rank`, `jurisdiction`) must be written from retrieval metadata: `doc.status = meta["status"]`, `doc.legal_rank = meta["legal_rank"]`, `doc.jurisdiction = meta["jurisdiction"]`.

**FR-8.4** UUID stability: derivation stays `uuid5(source_file|article)` — unchanged from current.

---

## 4. Non-Functional Requirements

**NFR-1 — Safety**: `parse_frontmatter()` must not raise under any input. All edge cases (no frontmatter, malformed YAML, binary content) must be caught and logged.

**NFR-2 — Idempotency**: re-running ingest on the same pinned commit must produce zero net changes to the DB (same hashes → embed skipped; same metadata → merge is a no-op).

**NFR-3 — No new dependencies** beyond `PyYAML` (already a transitive dependency of LangChain; verify presence, add to `requirements.txt` if missing) and `hashlib` (stdlib).

**NFR-4 — Backwards compatibility**: existing `metadata` JSONB column layout is preserved. The 9 original fields remain in place; new fields are additive. Old rows without `source_metadata` column get `'{}'` via the migration default.

**NFR-5 — Readability**: no new abstract base classes, no metaclasses, no plugin registries. Helper functions are plain functions in a single `metadata_helpers.py` module.

**NFR-6 — Test coverage**: all new pure functions (`parse_frontmatter`, `compute_content_hash`, `extract_legal_rank`, `normalize_status`, `derive_eli`) must have unit tests that can run without a DB or Cohere connection. `upsert_documents()` hash-skip path must be tested with a mock session.

---

## 5. Acceptance Criteria

| AC | Description |
|---|---|
| AC-1 | `parse_frontmatter("---\ntitle: X\n---\n# H1")` returns `({"title": "X"}, "\n# H1")` |
| AC-2 | `parse_frontmatter("no frontmatter here")` returns `({}, "no frontmatter here")` |
| AC-3 | `parse_frontmatter("---\n: broken\n---\n# H1")` returns `({}, original)` + WARNING logged |
| AC-4 | `compute_content_hash("  Hello  World  ")` == `compute_content_hash("hello world")` (normalization stable) |
| AC-5 | `normalize_status("in_force")` == `"vigente"`; `normalize_status("derogated")` == `"derogada"` |
| AC-6 | `normalize_status("unknown_val")` stores `"unknown_val"` and emits WARNING |
| AC-7 | `normalize_status(None)` == `""` (no error) |
| AC-8 | `extract_legal_rank({"rank": "real-decreto"}, "")` == `"real_decreto"` |
| AC-9 | `extract_legal_rank({}, "Ley Orgánica 3/2007")` == `"ley_organica"` |
| AC-10 | `derive_eli({"source": "https://boe.es/eli/es/rd/2023/001"})` returns `"eli/es/rd/2023/001"` |
| AC-11 | `derive_eli({})` returns `None` (not `""`) |
| AC-12 | Alembic `upgrade head` from migration 0002 adds 4 new columns + 4 new indexes cleanly |
| AC-13 | Alembic `downgrade base` removes all 4 columns and indexes without error |
| AC-14 | Re-running `ingest.py` on unchanged corpus: zero embed calls made (all skipped via hash match) |
| AC-15 | Re-running `ingest.py` on one changed article: exactly 1 embed call made for that article |
| AC-16 | `source_metadata` is populated for each document from frontmatter; `metadata` column still contains retrieval fields |
| AC-17 | `status`, `legal_rank`, `jurisdiction` real columns are populated from metadata for each document |

---

## 6. Files Affected

| File | Change type |
|---|---|
| `thermia-back/app/db/models.py` | Modify — add 4 columns |
| `thermia-back/alembic/versions/0003_metadata_refactor.py` | New — migration |
| `thermia-back/app/ingestion/metadata_helpers.py` | New — `parse_frontmatter`, `compute_content_hash`, `extract_legal_rank`, `normalize_status`, `derive_eli` |
| `thermia-back/scripts/ingest.py` | Modify — wire frontmatter parsing, two-layer metadata, hash-skip logic |
| `thermia-back/requirements.txt` | Modify — add `PyYAML>=6.0` if not already present |
| `thermia-back/tests/ingestion/test_metadata_helpers.py` | New — unit tests for all helpers |
| `thermia-back/tests/test_ingestion.py` | Modify — add hash-skip tests, source_metadata population tests |

> **Note**: `app/ingestion/` is a new sub-package. Create `thermia-back/app/ingestion/__init__.py`.

---

## 7. Architecture Decisions (rationale)

**ADR-1: Two JSONB columns, not nesting** — `metadata` stays flat for retrieval; `source_metadata` is a separate column. This keeps retrieval queries simple (`metadata->>'status'` vs `metadata->'retrieval'->>'status'`), allows independent GIN indexing, and avoids breaking existing rows.

**ADR-2: Three real columns for status/legal_rank/jurisdiction** — These three fields are the most likely WHERE-clause predicates in hybrid retrieval (filter by `status = 'vigente'` before vector search). B-tree indexes on VARCHAR columns outperform GIN jsonb_path_ops for equality filters on high-cardinality-key low-distinct-value columns.

**ADR-3: Active hash-skip (not store-only)** — The main cost driver for re-ingestion is Cohere API calls. Skipping embed when `content_hash` matches cuts re-run cost to near-zero. The SELECT-before-upsert overhead is negligible at the scale of tens-of-thousands of documents.

**ADR-4: ELI derived conservatively, never blocking** — ELI is absent from most pre-2000 BOE documents. Failing ingestion on a missing ELI would break the entire corpus. Store `NULL` and enrich later when the upstream `legalize-es` repo adds ELI fields.

**ADR-5: Status normalized to Spanish** — The retrieval layer and LLM prompts are Spanish-language. Storing `vigente`/`derogada` keeps the data model consistent with the domain language. The normalization dict is a single centralized function so it's trivially auditable.

**ADR-6: `app/ingestion/metadata_helpers.py` as a flat module** — All five helper functions are pure (no I/O, no DB, no Cohere). A single module is testable in isolation, readable, and avoids over-abstraction (no abstract base class, no registry pattern).
