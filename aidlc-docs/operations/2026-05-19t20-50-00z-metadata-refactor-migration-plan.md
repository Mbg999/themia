# Migration Plan: Metadata Refactor (0.1.0 → 0.2.0)

**Run:** 2026-05-19t20-50-00z-metadata-refactor
**Date:** 2026-05-19
**Deprecation deadline:** 2026-08-20

## Overview

This migration plan covers two breaking changes introduced in v0.2.0:

1. **Database schema change** (Alembic 0003): four new columns and four indexes on the
   `documents` table. This is a non-destructive, additive migration.
2. **API contract change**: the `fuentes` array in `/analyze` responses now returns nine
   fields per source instead of three. Consumers that expect only three fields must be
   updated.

---

## 1. Database Schema Migration (Alembic 0003)

### What changes

The `documents` table gains four new columns:

| Column | Type | Default | Purpose |
|---|---|---|---|
| `status` | `VARCHAR(32)` | `''` | Normalised vitality status (`vigente`, `parcialmente vigente`, `derogada`, `''`) |
| `legal_rank` | `VARCHAR(64)` | `''` | Normalised legal rank (`ley`, `real decreto`, `orden ministerial`, etc.) |
| `jurisdiction` | `VARCHAR(64)` | `''` | Jurisdiction (`estatal`, `autonómica`, etc.) |
| `source_metadata_` | `JSONB` | `{}` | Raw YAML frontmatter preserved verbatim |

Four indexes are created:

| Index | Column | Type | Notes |
|---|---|---|---|
| `ix_documents_status` | `status` | B-tree | Supports `only_active` filter |
| `ix_documents_legal_rank` | `legal_rank` | B-tree | Supports rank-based filtering |
| `ix_documents_hierarchy_path` | `metadata_->>'hierarchy_path'` | B-tree | Supports path-based queries |
| `ix_documents_metadata_gin` | `metadata_` | GIN | Full JSONB key search |

### Migration procedure

1. **Pre-migration**: ensure no active ingestion jobs are running.
2. Run `alembic upgrade head` from `thermia-back/`.
   - The upgrade uses `ADD COLUMN IF NOT EXISTS` — idempotent, safe to re-run.
   - Indexes are created with `CONCURRENTLY` — no exclusive table lock; reads and writes
     continue uninterrupted. This may take several minutes on large tables.
3. **Verify**: run `alembic check` — should report no pending revisions.
4. **Post-migration**: re-ingest the corpus to populate the new columns. Documents
   ingested before this migration will have `status=''`, `legal_rank=''`, and
   `source_metadata_={}` until re-ingested.

### Downgrade procedure

Run `alembic downgrade 0002`. This will:
- Drop the four new columns.
- Drop the four new indexes.

**Warning:** downgrade is destructive. Any data written to the new columns will be lost.
Take a database snapshot before downgrading in production.

### Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Index creation blocks table | Low | High | `CONCURRENTLY` flag eliminates exclusive lock |
| Re-ingestion overwrites valid embeddings | Low | Medium | `upsert_documents` guards `embedding` write with None check |
| Partial migration leaves schema inconsistent | Very Low | Medium | `IF NOT EXISTS` guards make upgrade idempotent |

---

## 2. API Contract Change: `fuentes` Nine-Field Shape

### What changes

The `/analyze` endpoint's `fuentes` response array has expanded from three fields to
nine:

**Before (v0.1.0 — three fields):**
```json
{
  "titulo": "Artículo 35",
  "articulo": "35",
  "seccion": "Derechos laborales"
}
```

**After (v0.2.0 — nine fields):**
```json
{
  "titulo": "Artículo 35",
  "articulo": "35",
  "seccion": "Derechos laborales",
  "ley_id": "BOE-A-2007-5415",
  "eli": "https://www.boe.es/eli/es/lo/2007/03/22/3",
  "status": "vigente",
  "legal_rank": "ley organica",
  "jurisdiction": "estatal",
  "hierarchy_path": "titulo-i/capitulo-ii"
}
```

### Deprecation timeline

| Date | Action |
|---|---|
| 2026-05-20 | v0.2.0 released. Nine-field shape is the current shape. |
| 2026-05-20 | Three-field shape deprecated. Warning added to API docs. |
| 2026-08-20 | **Deprecation deadline.** All consumers must be updated. |
| 0.3.0 (TBD) | Legacy three-field shape removed from API. |

### Consumer migration checklist

Consumers of the `/analyze` endpoint must:

- [ ] Update the `Fuente` / source interface/model to include the six new optional
  fields (`ley_id`, `eli`, `status`, `legal_rank`, `jurisdiction`, `hierarchy_path`).
- [ ] Handle `null` / empty string for new fields (not all documents have all fields).
- [ ] If displaying `eli` as a hyperlink: validate the URI scheme on the client side
  before rendering (defence-in-depth, even though the server already validates).
- [ ] If filtering by status or rank on the client: use the canonical normalised values
  (`vigente`, `parcialmente vigente`, `derogada`, `ley`, `real decreto`, etc.).

### Known consumers

| Consumer | Status | Owner |
|---|---|---|
| `thermia-front` Angular app | Updated in this run (v0.2.0) | This team |

No other known consumers of the `/analyze` API at this time. If you have an integration,
contact the team before 2026-08-20.

---

## 3. Corpus Re-ingestion

After applying the database migration, the existing corpus documents will have empty
values for `status`, `legal_rank`, `jurisdiction`, and `source_metadata_`. To populate
these fields:

```bash
cd thermia-back
python scripts/ingest.py --repo-path <path-to-legal-corpus>
```

The ingestion script uses `session.merge()` with the document's `law_id` as the merge
key. Re-ingestion updates metadata columns without re-computing embeddings if the
content hash has not changed (pending full activation of the hash-skip optimisation in
a future release).

**Estimated re-ingestion time:** depends on corpus size and Cohere API rate limits.
Monitor `logs/ingest.log` for progress.

---

## 4. Rollback Plan

If the migration must be rolled back after production deployment:

1. Stop the application server.
2. Run `alembic downgrade 0002`.
3. Redeploy v0.1.0 of the application.
4. The API will return the three-field `fuentes` shape again.

**Note:** data written to the new columns during the v0.2.0 period will be lost on
downgrade. This is acceptable because the new columns can be repopulated by re-ingestion.
