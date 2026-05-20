# ADR 0001: Two-Layer Metadata Architecture (Retrieval + Source)

**Run:** 2026-05-19t20-50-00z-metadata-refactor
**Date:** 2026-05-19
**Status:** Accepted

## Context

The Thermia Legal RAG system ingests Spanish legal Markdown documents that carry rich
YAML frontmatter (ELI identifiers, article numbers, legal rank, jurisdiction, status,
hierarchy paths, and more). The MVP stored only raw text and a generic unstructured
JSONB blob per document.

Two conflicting requirements emerged:

1. **Retrieval efficiency**: pgvector hybrid search needs to filter on a small number of
   stable, curated keys (status, law_id, legal_rank) without parsing arbitrary JSON at
   query time. These keys must be indexable.
2. **Provenance**: the original frontmatter is the authoritative source-of-truth for
   legal citations. Future auditors and legal teams need to trace exactly what metadata
   was in the source document at ingestion time.

A single JSONB column cannot satisfy both: curated indexable keys and raw preservation
are structurally different concerns.

## Decision

Introduce two JSONB columns on the `documents` table:

- **`metadata_`** (retrieval layer): populated by `build_metadata_payload` in
  `metadata_helpers.py`. Contains a fixed set of curated, normalised keys:
  `law_id`, `article`, `section`, `hierarchy_path`, `eli`, `status`, `legal_rank`,
  `jurisdiction`, `content_hash`. PostgreSQL indexes are created on the high-cardinality
  retrieval keys (`status`, `legal_rank`, `hierarchy_path`).
- **`source_metadata_`** (source layer): populated by storing `frontmatter` as-is
  (after YAML parsing). Preserves every key in the original frontmatter unchanged,
  including keys the retrieval layer does not consume.

The two layers are populated atomically during ingestion and are never merged. The
retrieval layer is the only one used by `searcher.py` and `context_builder.py`. The
source layer is only read for audit and provenance queries.

## Consequences

**Positive:**
- Retrieval filters (`only_active`, rank filters) operate on normalised values in
  `metadata_`, enabling efficient B-tree and GIN index use.
- Provenance is preserved: the raw frontmatter is never discarded or overwritten by
  normalisation.
- Adding a new curated retrieval key requires only a migration + helper update, not a
  schema redesign.
- The two layers have different stability contracts: `source_metadata_` is append-only,
  `metadata_` keys are versioned with the schema.

**Negative / Trade-offs:**
- Two JSONB columns increase storage per document. For the current corpus size
  (thousands of documents) this is negligible.
- Ingestion must populate both columns atomically; a partial write would leave provenance
  inconsistent. The `upsert_documents` function enforces this via `session.merge`.
- Future additions to the curated key set require a code change to `build_metadata_payload`,
  not just a data migration.

**Risks:**
- If `metadata_` normalisation introduces a bug (e.g., incorrect `normalize_status`
  mapping), the raw `source_metadata_` provides a recovery path for re-ingestion without
  re-downloading source documents.
