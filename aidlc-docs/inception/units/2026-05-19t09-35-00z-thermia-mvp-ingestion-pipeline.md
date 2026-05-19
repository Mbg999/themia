# Unit Spec: `ingestion-pipeline`
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp
**Layer:** 1 | **Dependencies:** `db-layer`

---

## Purpose
Populate the `documents` table from the [legalize-es](https://github.com/legalize-dev/legalize-es) GitHub corpus. A manually-executable CLI script that clones the repo, parses Spanish legal Markdown files into article-level chunks, generates Cohere embeddings, and upserts results idempotently.

## Responsibilities
- Clone `https://github.com/legalize-dev/legalize-es` (or pull if already present)
- Recursively scan all `.md` files
- Parse Markdown heading hierarchy into `{law, title, article}` structure
- Chunk each article (≤ 800 tokens → single chunk; > 800 → sub-chunks ≤ 512 tokens, overlap 50)
- Prefix every chunk text: `[LAW X - ARTICLE Y - TITLE Z]\n\narticle text...`
- Generate 1024-dimensional Cohere embeddings (`embed-multilingual-v3.0`, `input_type="search_document"`)
- Upsert chunks keyed on `(source_file, article)` — idempotent on re-runs
- Populate `tsvector` via `to_tsvector('spanish', content)`
- Print per-file progress; handle per-file errors without aborting the full run
- Support `--reset` flag to truncate before ingesting

## Public Interfaces
None exposed externally. This is a standalone CLI tool.

**CLI entry point:**
```
python3 thermia-back/scripts/ingest.py [--reset]
```

## Internal Dependencies
| Unit | What it consumes |
|---|---|
| `db-layer` | `get_engine()` connection factory + `Document` ORM model |

## External Dependencies
| Package | Version (pinned) | Purpose |
|---|---|---|
| `cohere` | latest stable | Embedding API (`embed-multilingual-v3.0`) |
| `tiktoken` or `transformers` tokenizer | latest stable | Token counting for chunk threshold |
| `gitpython` | latest stable | Repo clone/pull |
| `mistune` or `markdown-it-py` | latest stable | Markdown heading parser |

## Tasks
| Task | Description |
|---|---|
| ING-T1 | GitHub clone step (gitpython; pull if exists) |
| ING-T2 | `.md` file scanner (recursive, relative paths) |
| ING-T3 | Markdown legal structure parser (H1=law, H2=title, H3+=article) |
| ING-T4 | Article chunker (800-token threshold; sub-chunks ≤ 512 tokens, overlap 50; chunk prefix format) |
| ING-T5 | Cohere embedding client (batch calls; `search_document` input type; 1024d verification) |
| ING-T6 | Upsert logic (keyed on `source_file + article`; tsvector population) |
| ING-T7 | CLI entry point with `--reset` flag + progress output |
| ING-T8 | Unit tests: parser, chunker (boundary conditions), upsert idempotency |

## Acceptance Criteria (rolled up)
- [ ] `python3 scripts/ingest.py` runs end-to-end; prints per-file progress
- [ ] `python3 scripts/ingest.py --reset` truncates `documents` before ingesting
- [ ] First run inserts N rows; second run with same data produces the same N rows
- [ ] Articles ≤ 800 tokens produce exactly 1 chunk; articles > 800 tokens produce sub-chunks each ≤ 512 tokens
- [ ] Sub-chunks have 50-token overlap between consecutive chunks
- [ ] Chunk text is prefixed with `[LAW X - ARTICLE Y - TITLE Z]\n\n`
- [ ] `chunk_type = "article"` for single chunks; `"sub_article"` for sub-chunks
- [ ] Cohere embed called with `model="embed-multilingual-v3.0"`, `input_type="search_document"`
- [ ] Embedding vectors are 1024-dimensional
- [ ] `tsvector` column populated with `to_tsvector('spanish', content)`
- [ ] Per-file errors logged; script does not abort on single-file failure
- [ ] `pytest tests/test_ingestion.py` passes (parser edge cases + chunker bounds + upsert idempotency)

## Definition of Done
- All tasks complete with green tests
- Script verified to run against a real (or Docker-mounted) Postgres instance
- No `COHERE_API_KEY` hardcoded; read from env var
- `--reset` verified to produce fresh identical output on re-run
