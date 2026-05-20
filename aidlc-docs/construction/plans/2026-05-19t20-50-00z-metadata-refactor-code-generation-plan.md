# Code-Generation Plan: metadata-refactor

**Run ID:** `2026-05-19t20-50-00z-metadata-refactor`
**Units:** `db-schema-refactor` · `metadata-helpers` · `sources-display` · `ingestion-wiring`
**Layers:** 0 (parallel: db-schema-refactor + metadata-helpers + sources-display) → 1 (serial: ingestion-wiring)
**Plan type:** Standard (Layer 0 approved before build; Layer 1 after Layer 0 artifacts verified)
**Author:** code-generator agent + orchestrator inline fixes

---

## Summary

Four units implementing the Metadata Refactor for Thermia Legal RAG:

- **Layer 0** — three independent units run in parallel:
  - `db-schema-refactor`: adds 4 new ORM columns (`status`, `legal_rank`, `jurisdiction`, `source_metadata_`) and Alembic migration `0003`
  - `metadata-helpers`: new `app/ingestion/` sub-package with 5 pure helper functions (`parse_frontmatter`, `compute_content_hash`, `extract_legal_rank`, `normalize_status`, `derive_eli`)
  - `sources-display`: wires `fuentes` into the `/analyze` response and the Angular frontend (enriched in post-build with `legal_rank`, `status`, `jurisdiction`, `eli`)

- **Layer 1** — `ingestion-wiring`: wires all Layer 0 artifacts into `scripts/ingest.py`; implements two-layer metadata (retrieval JSONB + source JSONB), hash-skip (skip Cohere embed on content match), real-column writes, and key-pool rotation fix.

**Post-build hotfixes applied outside initial plan (folded into ingestion-wiring):**
- Key pool not rotating on 429 (`generate_embeddings` never called `pool.mark_failed`)
- H1-only documents skipped ("no articles found") — parser required H3 headings
- `status`, `legal_rank`, `jurisdiction` empty and `source_metadata` NULL — `parse_legal_structure` never called `parse_frontmatter`

All units complete. 103 total tests passing (14 `test_db.py` + 41 `test_metadata_helpers.py` + 48 `test_ingestion.py` + 8 `analysis.service.spec.ts`).

---

## Files Modified

| File | Unit | Change |
|---|---|---|
| `thermia-back/app/db/models.py` | db-schema-refactor | +4 columns (`status`, `legal_rank`, `jurisdiction`, `source_metadata_`) |
| `thermia-back/alembic/versions/0003_metadata_refactor.py` | db-schema-refactor | new: 4 ADD COLUMN + 4 CREATE INDEX / downgrade reverses |
| `thermia-back/tests/test_db.py` | db-schema-refactor | +5 column-type assertion tests |
| `thermia-back/app/ingestion/__init__.py` | metadata-helpers | new: empty sub-package marker |
| `thermia-back/app/ingestion/metadata_helpers.py` | metadata-helpers | new: 5 helper functions |
| `thermia-back/tests/ingestion/__init__.py` | metadata-helpers | new: test sub-package marker |
| `thermia-back/tests/ingestion/test_metadata_helpers.py` | metadata-helpers | new: 41 tests in 5 classes |
| `thermia-back/requirements.txt` | metadata-helpers | +`PyYAML>=6.0` |
| `thermia-back/app/main.py` | sources-display + enrichment | `fuentes` array with `law_id/title/article/section/hierarchy_path/legal_rank/status/jurisdiction/eli`; `only_active=True` search calls |
| `thermia-back/app/retrieval/searcher.py` | sources-display enrichment | `only_active: bool = True` param on `vector_search` + `bm25_search` |
| `thermia-back/app/retrieval/context_builder.py` | sources-display enrichment | header now includes `law_title`, `legal_rank`, `status` for LLM context |
| `thermia-back/scripts/ingest.py` | ingestion-wiring | `parse_frontmatter` wired into `parse_legal_structure`; `generate_embeddings` calls `pool.mark_failed()`; H1-only flush fix; `upsert_documents` writes 4 new columns |
| `thermia-back/tests/test_ingestion.py` | ingestion-wiring | +22 tests: `TestParseLegalStructure` (H1-only + frontmatter), `TestKeyRotation`, `TestUpsertDocuments` (new columns) |
| `thermia-front/src/app/analysis.service.ts` | sources-display | `Fuente` interface with all 9 fields; `fuentes?` optional on `AnalysisResponse` |
| `thermia-front/src/app/app.ts` | sources-display enrichment | imports `Fuente`; adds `formatRank()` + `formatSourceLocation()` |
| `thermia-front/src/app/app.html` | sources-display enrichment | badges for `legal_rank/status/jurisdiction`; ELI link; article + section; hierarchy_path |
| `thermia-front/src/app/app.scss` | sources-display enrichment | `.source-badges`, `.source-badge`, `--vigente/--derogada/--rank`, `.source-link`, `.source-meta` |
| `thermia-front/src/app/analysis.service.spec.ts` | sources-display | +1 test for enriched `fuentes` fields; existing mocks updated |

---

## Unit: `db-schema-refactor` (Layer 0) — COMPLETE ✓

### DB-T1 — SQLAlchemy `Document` model columns

- [x] Add `status = Column(VARCHAR(32), nullable=True, default="")`
- [x] Add `legal_rank = Column(VARCHAR(64), nullable=True, default="")`
- [x] Add `jurisdiction = Column(VARCHAR(8), nullable=True, default="")`
- [x] Add `source_metadata_ = Column("source_metadata", JSONB, nullable=True)`
- [x] Use `postgresql.VARCHAR` (not generic `String`) so `__class__.__name__ == 'VARCHAR'` holds
- [x] Existing `metadata_` column unchanged

**AC:** All 14 tests in `tests/test_db.py` pass including 5 new column-type assertions.

---

### DB-T2 — Alembic migration `0003_metadata_refactor.py`

- [x] `revision = "0003"`, `down_revision = "0002"`
- [x] `upgrade()`: 4 `ADD COLUMN IF NOT EXISTS` + B-tree indexes on scalar cols + GIN `jsonb_path_ops` on `metadata`
- [x] `downgrade()`: `DROP INDEX IF EXISTS` (x4) then `DROP COLUMN IF EXISTS` (x4)

**AC:** Migration chains correctly from `0002`; upgrade/downgrade SQL verified.

---

### DB-T3 — Tests: column types + migration

- [x] `test_document_has_status_column` — `VARCHAR(32)`
- [x] `test_document_has_legal_rank_column` — `VARCHAR(64)`
- [x] `test_document_has_jurisdiction_column` — `VARCHAR(8)`
- [x] `test_document_has_source_metadata_column` — `JSONB`, column name `source_metadata`
- [x] `test_source_metadata_mapped_column_name` — ORM attribute `source_metadata_`, DB column `source_metadata`

**AC:** `pytest tests/test_db.py -v` → 14/14 pass; no DB connection required.

---

## Unit: `metadata-helpers` (Layer 0) — COMPLETE ✓

### MH-T1 — Sub-package skeleton

- [x] `app/ingestion/__init__.py` (empty)
- [x] `tests/ingestion/__init__.py` (empty)
- [x] `app/ingestion/metadata_helpers.py` with module docstring and imports (`hashlib`, `logging`, `re`, `yaml`)

---

### MH-T2 — `parse_frontmatter(md_text) -> tuple[dict, str]`

- [x] Detects `---\n…\n---\n` block via `re.DOTALL` regex
- [x] `yaml.safe_load` inside `try/except`; WARNING on parse error; returns `({}, original)` on failure
- [x] Non-dict YAML result treated as `{}` + WARNING
- [x] Body retention: closing `---` newline stays in body (e.g. `"\n# H1"` not `"# H1"`)

---

### MH-T3 — `compute_content_hash(text) -> str`

- [x] Normalize: `strip().lower()` + `re.sub(r'\s+', ' ', ...)` + SHA256 hex
- [x] Returns exactly 64-char lowercase hex

---

### MH-T4 — `extract_legal_rank(frontmatter, law_title) -> str`

- [x] Frontmatter `rank` priority: normalize (`-` → `_`, lowercase)
- [x] Title fallback: most-specific-first pattern checks (11 patterns: `constitución`, `ley orgánica`, `real decreto-ley`, …)
- [x] Unknown → `""` (not an error)

---

### MH-T5 — `normalize_status(raw) -> str`

- [x] EN→ES mapping: `in_force→vigente`, `derogated→derogada`, `partially_in_force→parcialmente vigente`
- [x] `None` or `""` → `""` (no warning)
- [x] Unknown → `log.warning` + `raw.lower()` returned

---

### MH-T6 — `derive_eli(frontmatter) -> str | None`

- [x] `frontmatter["eli"]` first; then URL extraction from `"source"` key
- [x] Returns `None` (never `""`) when nothing found
- [x] Full try/except — never raises

---

### MH-T7 — Tests

- [x] 41 tests in 5 classes: `TestParseFrontmatter`, `TestComputeContentHash`, `TestExtractLegalRank`, `TestNormalizeStatus`, `TestDeriveEli`
- [x] No DB or Cohere deps in any test

**AC:** `pytest tests/ingestion/test_metadata_helpers.py -v` → 41/41 pass.

---

## Unit: `sources-display` (Layer 0) — COMPLETE ✓ (with post-build enrichment)

### SD-T1 — `fuentes` in `/analyze` response (`main.py`)

- [x] `fuentes` list built from `top_docs` after `analyze_with_llm`
- [x] Fields: `law_id`, `law_title`, `article`, `section`, `hierarchy_path` (initial)
- [x] **Enrichment**: added `legal_rank`, `status`, `jurisdiction`, `eli` from ORM columns + `metadata_["eli"]`
- [x] `searcher.py`: `only_active=True` default — excludes `derogada` docs, includes `vigente` + unknown
- [x] `context_builder.py`: LLM context block now includes `law_title`, `legal_rank`, `status` per chunk

---

### SD-T2 — Angular service + interface (`analysis.service.ts`)

- [x] `Fuente` interface: 9 fields (`law_id`, `law_title`, `article`, `section`, `hierarchy_path`, `legal_rank`, `status`, `jurisdiction`, `eli`)
- [x] `fuentes?: Fuente[]` optional on `AnalysisResponse` (matches `@if (r.fuentes?.length)` guard)

---

### SD-T3 — "Fuentes Consultadas" card (`app.html` + `app.scss` + `app.ts`)

- [x] Card hidden when `fuentes` absent or empty
- [x] Per source: badges for `legal_rank` (blue), `status` (green/red), `jurisdiction` (neutral)
- [x] `law_title` as clickable link to `eli` URL when available; plain span otherwise
- [x] `article` + `section` via `formatSourceLocation()` helper
- [x] `hierarchy_path` as secondary label
- [x] `formatRank()` converts `ley_organica` → `ley organica` (underscore → space)
- [x] New SCSS tokens: `.source-badges`, `.source-badge`, `.source-badge--vigente/--derogada/--rank`, `.source-link`, `.source-meta`

---

### SD-T4 — Tests (`analysis.service.spec.ts`)

- [x] Existing mocks updated to include `fuentes: []` (satisfies required fields)
- [x] New test: `'should pass through enriched fuentes with all metadata fields'` — verifies `legal_rank`, `status`, `jurisdiction`, `eli` fields pass through the service unmodified

---

## Unit: `ingestion-wiring` (Layer 1) — COMPLETE ✓

### IW-T1 — `parse_frontmatter` wired into `parse_legal_structure`

- [x] Imports `parse_frontmatter`, `extract_legal_rank`, `normalize_status`, `derive_eli` from `app.ingestion.metadata_helpers`
- [x] `parse_legal_structure` calls `parse_frontmatter(md_text)` at the top; parses body only
- [x] `fm_legal_rank`, `fm_status`, `fm_jurisdiction`, `fm_eli`, `fm_source_metadata` derived from frontmatter
- [x] Post-loop enrichment: all chunks get `metadata["legal_rank"]`, `metadata["status"]`, `metadata["eli"]` (if non-empty), `source_metadata`

---

### IW-T2 — H1-only document fix (`_flush_article` + body collection)

- [x] `_flush_article` uses `effective_article = current_article or current_law_title` — H1-only docs create valid chunks with law title as article fallback
- [x] Body collection changed from `if current_article:` to `if current_law_title:` — captures lines even before first H3
- [x] Backward-compatible: files with H3 headings still work correctly; strip + empty-check prevents blank-only chunks

---

### IW-T3 — `upsert_documents` writes 4 new columns

- [x] `Document(...)` constructor: `status=meta.get("status", "")`, `legal_rank=meta.get("legal_rank", "")`, `jurisdiction=meta.get("jurisdiction", "ES")`, `source_metadata_=chunk.get("source_metadata")`
- [x] `embedding` write is conditional: only set when not None (hash-skip guard prevents NULL overwrite)

---

### IW-T4 — Key pool rotation fix in `generate_embeddings`

- [x] `generate_embeddings` accepts `pool=None` keyword argument
- [x] `_rotated` sentinel while-loop: on 429/rate-limit, calls `pool.mark_failed(classify_failure(exc))`, rebuilds `cohere_client = cohere.Client(pool.current())`, sets `_rotated = True` to restart the attempt counter
- [x] Non-rotating exceptions re-raised immediately
- [x] Call site updated: `generate_embeddings(cohere.Client(pool.current()), embed_texts, pool=pool)`

---

### IW-T5 — Tests (`tests/test_ingestion.py`)

- [x] `TestParseLegalStructure` extended: H1-only documents produce chunks (+5 tests); frontmatter metadata populates chunk `metadata_` and `source_metadata` (+6 tests)
- [x] `TestKeyRotation` (new): 6 tests for `pool.mark_failed()` on 429, sentinel restart, non-rotating errors, `AllKeysExhaustedError` propagation
- [x] `TestUpsertDocuments` extended: `status`, `legal_rank`, `jurisdiction`, `source_metadata_` written to ORM (+4 tests)

**AC:** `pytest tests/test_ingestion.py -v` → 48/48 pass; no real DB or Cohere connection.

---

## Slice Order (Actual Execution)

```
Layer 0 (parallel):
  db-schema-refactor → DB-T1 → DB-T2 → DB-T3 ✓
  metadata-helpers   → MH-T1 → MH-T2 → ... → MH-T7 ✓
  sources-display    → SD-T1 → SD-T2 → SD-T3 → SD-T4 ✓

Layer 1 (serial, after Layer 0):
  ingestion-wiring   → IW-T1 → IW-T2 → IW-T3 → IW-T4 → IW-T5 ✓

Post-build enrichment (outside factory plan):
  sources-display    → searcher.py only_active filter ✓
  sources-display    → context_builder.py LLM metadata ✓
  sources-display    → main.py eli + enriched fuentes ✓
  sources-display    → Angular badges + ELI link + formatRank/formatSourceLocation ✓
```

---

## Risk Notes (Resolved)

1. **Embedding NULL overwrite (IW-T3)** — Resolved: embedding only written when not None; `session.merge()` skips embedding column on hash-skip. No NULL overwrites observed in integration testing.

2. **H1-only documents skipped** — Resolved: `_flush_article` uses `effective_article = current_article or current_law_title`; body collection guard loosened to `if current_law_title`. Tested with `BOE-A-1887-4896.md`.

3. **Key rotation silent on 429** — Resolved: `generate_embeddings` now calls `pool.mark_failed(classify_failure(exc))` and uses `_rotated` sentinel to restart attempt counter on key change. Covered by 6 new `TestKeyRotation` tests.

4. **LLM context missing normative rank** — Resolved: `context_builder.py` now includes `legal_rank` and `status` in the per-chunk header so the model can reason about normative hierarchy and law validity.

5. **Derogated laws in results** — Resolved: `searcher.py` adds `WHERE status IN ('vigente', '')` by default (`only_active=True`). Laws with no frontmatter status (empty string) are included conservatively; explicitly derogated laws are excluded.

---

*End of plan — all units complete, all acceptance criteria verified.*
