# Migration Plan: Cohere → Ollama BGE-M3

**Run:** 2026-05-20t08-41-48z-bge-m3-migration
**Date:** 2026-05-20
**Version:** 0.2.0 → 0.3.0

---

## 1. Summary

Thermia's embedding backend is migrating from Cohere `embed-multilingual-v3.0` (cloud
API) to self-hosted Ollama `bge-m3` (1024-dim). The code migration is complete as of
this run. This document covers:

- Environment variable changes required in all deployment targets
- Re-ingestion of pgvector data (mandatory — embeddings are not cross-compatible)
- Rollback procedure
- Cohere deprecation timeline and cleanup actions

---

## 2. Environment Variable Changes

| Variable | Old value | New value | Action |
|---|---|---|---|
| `COHERE_API_KEYS` | `key1,key2,...` | _not used_ | **Remove** from all envs by 2026-08-20 |
| `OLLAMA_HOST` | _not set_ | `https://ollama.cvbooster.es` | **Add** before deploying v0.3.0 |
| `OLLAMA_MODEL` | _not set_ | `bge-m3` (or omit to use default) | Optional — defaults to `bge-m3` |

`OLLAMA_HOST` is validated at startup. If it is absent or points to a plain `http://`
non-localhost address, the FastAPI server will refuse to start.

### `.env.example` update

```dotenv
# Embedding backend (Ollama BGE-M3)
OLLAMA_HOST=https://ollama.cvbooster.es
OLLAMA_MODEL=bge-m3        # optional, default: bge-m3

# COHERE_API_KEYS=...       # REMOVED — no longer used
```

---

## 3. Re-ingestion of pgvector Data

### Why re-ingestion is mandatory

Cohere `embed-multilingual-v3.0` and BGE-M3 produce vectors in different embedding
spaces. Cosine similarity between a BGE-M3 query vector and a Cohere document vector is
meaningless. If old and new vectors coexist in the `documents` table, semantic search
will silently return degraded or incorrect results.

### Re-ingestion procedure

1. **Deploy v0.3.0** to the target environment with `OLLAMA_HOST` set and validated.
2. **Verify Ollama connectivity**: `curl https://ollama.cvbooster.es/api/version` should
   return a version JSON.
3. **Truncate or mark old embeddings** (choose one):
   - Option A — full re-ingest with overwrite: run `scripts/ingest.py` over the full
     corpus. `upsert_documents` will overwrite existing rows by primary key. This is safe
     and idempotent but may take hours on large corpora.
   - Option B — zero-downtime: add a `embedding_model` column to track which model
     produced each embedding, then migrate documents in batches while the old vectors
     continue serving queries. Promote the new column as the default after re-ingestion
     completes. This approach requires an Alembic migration not included in this run.
4. **Verify retrieval quality** after re-ingestion: run the existing MRR/recall
   regression suite against a curated query set. A >5% drop in MRR@10 relative to the
   Cohere baseline warrants investigation before rolling out to production.
5. **Remove `COHERE_API_KEYS`** from the environment after confirming re-ingestion
   success.

### Estimated re-ingestion time

Based on the current corpus size and Ollama throughput:

- Ollama BGE-M3 processes ~50 chunks/sec on the target node (single-threaded).
- A corpus of 10,000 chunks takes approximately 3-4 minutes.
- The ingestion script does not currently support parallelism. If throughput is
  insufficient, a batched parallel variant should be developed.

---

## 4. Rollback Procedure

If v0.3.0 must be rolled back to v0.2.0 (Cohere):

1. **Revert the application code** to the v0.2.0 tag:
   ```bash
   git checkout v0.2.0
   ```
2. **Restore environment variables**:
   - Set `COHERE_API_KEYS` to the original key list.
   - Remove or unset `OLLAMA_HOST` and `OLLAMA_MODEL`.
3. **Re-ingest with Cohere** if documents were re-ingested with BGE-M3 (otherwise the
   existing Cohere embeddings are still in the database and are immediately usable).
4. **No schema rollback required**: the `documents` table schema did not change in this
   migration.

### Rollback window

A rollback is feasible within the first 7 days of v0.3.0 deployment, provided:
- The Cohere API keys have not been revoked.
- The original Cohere embeddings have not been overwritten (re-ingestion not yet run).

After re-ingestion with BGE-M3 completes, rollback requires a full re-ingestion with
Cohere, which may take hours. Plan accordingly.

---

## 5. Cohere Deprecation Timeline

| Date | Action |
|---|---|
| **2026-05-20** | Code migration complete. `cohere` package removed from `requirements.txt`. v0.3.0 released. |
| **2026-06-20** | All staging/QA environments must have `COHERE_API_KEYS` removed and `OLLAMA_HOST` verified. Re-ingestion in staging must be complete. |
| **2026-07-20** | Production re-ingestion with BGE-M3 must be complete. Cohere API keys should be deactivated in the Cohere dashboard (not just removed from env). |
| **2026-08-20** | Hard deprecation deadline: `COHERE_API_KEYS` env var removed from all deployment configs, CI secrets, and documentation. Any remaining Cohere API key subscriptions should be cancelled. |
| **2026-08-20** | Three-field `fuentes` shape (`titulo`, `articulo`, `seccion`) also reaches its deprecation deadline (per 0.2.0 release notes). |

---

## 6. CI/CD Considerations

The existing `.github/workflows/ci.yml` workflow runs pytest with `THERMIA_MODE=test`.
All external services (including the embedder) are mocked in the test suite. No changes
to the CI workflow are required for the embedder migration.

The comment in `ci.yml` still reads "No Cohere or SSH credentials needed for unit tests
(all external calls are mocked)." This comment should be updated to replace the Cohere
reference when the file is next edited:

```yaml
# No Ollama or SSH credentials needed for unit tests (all external calls are mocked).
```

This is a cosmetic change and does not affect CI correctness.

---

## 7. Affected Files

| File | Change | Status |
|---|---|---|
| `thermia-back/app/retrieval/embedder.py` | Full rewrite: Cohere → Ollama singleton | Done |
| `thermia-back/app/retrieval/key_pool.py` | Removed Cohere key-rotation logic | Done |
| `thermia-back/scripts/ingest.py` | `generate_embeddings()` uses `ollama.Client` | Done |
| `thermia-back/app/main.py` | Lifespan calls `_validate_host()` at startup | Done |
| `thermia-back/requirements.txt` | `cohere` removed, `ollama` pinned | Done |
| `thermia-back/tests/retrieval/test_embedder.py` | Updated for new singleton API | Done |
| `thermia-back/tests/retrieval/test_key_pool.py` | Updated for stripped KeyPool | Done |
| `thermia-back/tests/test_ingestion.py` | Updated for Ollama mock | Done |
| `.env.example` | Add `OLLAMA_HOST`, comment out `COHERE_API_KEYS` | Pending — do manually |
