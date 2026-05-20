# ADR 0002: `only_active` Filter Uses IN-List Semantics, Not a Boolean Column

**Run:** 2026-05-19t20-50-00z-metadata-refactor
**Date:** 2026-05-19
**Status:** Accepted

## Context

Spanish legal documents have nuanced vitality states: a law can be `vigente` (in force),
`parcialmente vigente` (partially in force — some articles derogated), `derogada`
(fully derogated), or have an unknown/empty status imported from legacy frontmatter.

The retrieval API needs a flag — `only_active` — to exclude derogated documents from
search results. Two design options were considered:

1. **Boolean column** (`is_active BOOLEAN`): simple, indexed efficiently, but requires
   a schema migration every time a new status value is introduced (e.g., `suspendida`,
   `en_vigor_provisional`). Also loses the nuance of `parcialmente vigente` — a document
   that is partially in force is neither fully active nor derogated.

2. **IN-list on the `status` text column**: the filter is expressed as
   `Document.status.IN(['vigente', 'parcialmente vigente', ''])`. The allowlist is
   defined in code alongside `normalize_status`, so adding a new allowed status requires
   only a code change, not a schema migration.

## Decision

Use an IN-list filter on the `metadata_['status']` value (surfaced as the `status`
column via normalisation). The active-status allowlist is:

```python
ACTIVE_STATUSES = ['vigente', 'parcialmente vigente', '']
```

The empty string `''` is included to pass through documents whose status could not be
determined at ingestion time, avoiding silent exclusion of corpus documents that predate
the status-normalisation feature.

A B-tree index on `documents.status` is created by migration 0003 to ensure the IN
filter is efficient even on large corpora.

## Consequences

**Positive:**
- New status values (e.g., `en_vigor_provisional`) can be added to or removed from the
  allowlist without a PostgreSQL schema migration — only a code change + redeploy.
- `parcialmente vigente` laws appear in results, which is legally correct: a law that
  is partially in force is still a valid source for article-level citation.
- The empty-string passthrough prevents silent data loss for documents ingested before
  status normalisation was implemented.

**Negative / Trade-offs:**
- The allowlist lives in application code (`searcher.py`), not in the database. If a
  future team adds a new status value to the normaliser without updating the filter list,
  documents with the new status will be silently excluded.
- A boolean column would be slightly more efficient for the common case (most queries
  will use `only_active=True`). The difference is negligible at current corpus scale.

**Mitigation:**
- The allowlist constant and `normalize_status` mappings are co-located in
  `metadata_helpers.py` and `searcher.py` with a comment cross-referencing both. Any
  PR that modifies `normalize_status` must also review the IN-list in `searcher.py`.
