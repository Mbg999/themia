# Requirement Verification Questions
**Run:** `2026-05-19t20-50-00z-metadata-refactor`
**Stage:** Requirements Analyst — Pass 1
**Date:** 2026-05-19

---

## Context Summary (what I read before asking)

- **Current DB schema**: single `metadata JSONB` column on the `documents` table — holds all 9 fields flat.
- **Current idempotency key**: `uuid5(source_file|article)` in `upsert_documents()` — stable across re-runs.
- **Current parser**: `parse_legal_structure()` reads raw Markdown only — **does not strip or parse YAML frontmatter** at all. If the frontmatter sits between `---` markers before the `# H1`, it's currently silently skipped or treated as body text.
- **Alembic state**: 2 migrations (`0001_initial`, `0002_fix_ivfflat_lists`). No existing columns for `status`, `law_id`, `legal_rank`, etc.
- **The `metadata_` column** is a single JSONB blob. The user request asks us to split into two layers: retrieval metadata + source metadata.

---

## Question 1: DB split — one column or two?

**Background**: You asked to split metadata into two layers (retrieval + source). There are two clean ways to implement this in PostgreSQL:

**Option A — Two JSONB columns** (add `source_metadata JSONB DEFAULT '{}'` alongside the existing `metadata JSONB`)
- Clean separation at the DB level; retrieval metadata stays small and indexable; source metadata never pollutes WHERE clauses
- Requires a new Alembic migration to add the column
- The ORM model gets a second `source_metadata_` column

**Option B — Nest within the existing `metadata` JSONB** (e.g. `metadata.retrieval = {...}` and `metadata.source = {...}`)
- No schema migration needed — backwards-compatible with existing rows
- More complex jsonb path expressions in queries: `metadata->'retrieval'->>'status'` vs `metadata->>'status'`
- Harder to index specific fields later

**Which do you prefer?**

[Answer]: A

---

## Question 2: Which retrieval metadata fields should become indexed relational columns?

**Background**: You asked us to "propose whether some fields should become indexed relational columns." Rather than decide for you, we want to confirm the approach before writing the migration.

Our proposal: promote **3 fields** to indexed columns (most likely to appear in WHERE clauses for legal retrieval):

| Proposed column | Type | Rationale |
|---|---|---|
| `status` | `VARCHAR(32)` | filter vigente vs derogada — high selectivity |
| `legal_rank` | `VARCHAR(64)` | filter by norm type (Ley vs Real Decreto) |
| `jurisdiction` | `VARCHAR(8)` | currently always 'ES' but will grow |

Everything else stays in `metadata JSONB` (or its retrieval sub-key).

**Option A — Promote those 3 columns** (add `status`, `legal_rank`, `jurisdiction` as real columns with B-tree indexes)
**Option B — Keep everything in JSONB** and add a GIN index on the retrieval JSONB key for flexible filtering
**Option C — Promote only `status`** (the one field you explicitly said is critical for filtering obsolete norms)

[Answer]: A

---

## Question 3: Content hash idempotency — complement or replace uuid5?

**Background**: You asked for `content_hash` (SHA256 of normalized article text) to "avoid unnecessary re-embedding in future iterations." The current idempotency is via `uuid5(source_file|article)` as the primary key — re-runs merge on the same UUID.

There are two ways to wire content_hash:

**Option A — Store-only** (hash goes in retrieval metadata; UUID derivation stays `uuid5(source_file|article)`; future code can check hash before calling Cohere embed)
- Simpler to implement now; hash is there for future use but the ingest loop doesn't yet skip unchanged chunks
- No change to upsert logic

**Option B — Active skip** (ingest loop queries existing `content_hash` before embedding; skips the embed call if hash matches; still upserts metadata-only if metadata changed)
- Saves Cohere API calls on re-runs with unchanged content
- More complex: requires a SELECT before each upsert to check the stored hash

**Which do you want for the MVP?**

[Answer]: B

---

## Question 4: Status normalization — Spanish or raw from frontmatter?

**Background**: The `legalize-es` frontmatter uses English values like `status: "in_force"` and `status: "derogated"`. Your retrieval metadata spec lists Spanish strings (`vigente`, `derogada`, `parcialmente vigente`).

**Option A — Normalize during ingestion** (map `in_force` → `vigente`, `derogated` → `derogada`, `partially_in_force` → `parcialmente vigente`; unknown values → stored as-is with a WARNING log)
- Clean Spanish status values in the DB; consistent with the Spanish legal domain
- Requires a normalization table/dict in the parser

**Option B — Store raw frontmatter value** (`in_force` stays `in_force`; your retrieval code filters on English values)
- Simpler ingestion; avoids wrong mappings for edge-case statuses
- Inconsistent with the Spanish status names in your spec

[Answer]: A, Unknown values should be preserved as-is. Emit a WARNING log for unknown statuses. Normalization logic should live in a small centralized helper function.

---

## Question 5: `eli` field — mapping or leave empty?

**Background**: Your retrieval metadata schema includes an `eli` field (European Legislation Identifier, a standardized URI like `eli/es/rd/2023/001`). The `legalize-es` frontmatter **does not include an ELI field** — it has `identifier` (the BOE ID like `BOE-A-1835-2348`) and `source` (a BOE URL).

**Option A — Leave `eli` empty/null** if no ELI is present in the frontmatter (most documents in the 1800s won't have one)
**Option B — Derive ELI from existing fields** if possible (attempt to parse from `source` URL or construct from `identifier`)
**Option C — Drop `eli` from MVP scope** (remove it from retrieval metadata entirely; add it when legalize-es provides it)

[Answer]: B — attempt to derive ELI conservatively from source/identifier, otherwise store NULL without failing ingestion.

---

## Question 6: Frontmatter stripping from article content

**Background**: Currently `parse_legal_structure()` does **not** strip the YAML frontmatter block (the `---...---` preamble). For the BOE-A-1835-2348 example, the frontmatter lines would appear as body text if an H3 heading is encountered immediately after them. The H1 heading comes after the closing `---`, so in practice the frontmatter lines are currently discarded (no H3 is open when they're seen), but this is brittle.

**Should we explicitly strip frontmatter before parsing?**

**Option A — Yes, strip frontmatter explicitly** (detect and remove the leading `---...---` block before calling `parse_legal_structure`; store extracted fields in metadata)
**Option B — Rely on existing behaviour** (current parser effectively ignores frontmatter since it appears before the first H1; no change needed here)

[Answer]: A — explicitly strip YAML/frontmatter before parsing, extract it into metadata, and ensure it never enters chunked content or embeddings for robustness and correctness.

