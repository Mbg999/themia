# ADR 0001: Ollama BGE-M3 as the Embedding Backend

**Run:** 2026-05-20t08-41-48z-bge-m3-migration
**Date:** 2026-05-20
**Status:** Accepted

## Context

The Thermia Legal RAG system used Cohere `embed-multilingual-v3.0` as its sole embedding
provider since the MVP (v0.1.0). The key pool in `app/retrieval/key_pool.py` managed
rotation across multiple Cohere API keys, and `scripts/ingest.py` called the Cohere batch
embed API to populate pgvector.

Several constraints made this arrangement unsustainable:

1. **Cost**: Cohere API fees for continuous ingestion and re-ingestion of the Spanish
   legal corpus were deemed too high relative to the project budget.
2. **Vendor lock-in**: the key pool, ingestion pipeline, and embedder were all hard-coded
   to Cohere types. Switching providers required changes across at least four files.
3. **Self-hosting feasibility**: a self-hosted Ollama node at
   `https://ollama.cvbooster.es` is already available and running the `bge-m3` model,
   which produces 1024-dimensional multilingual embeddings — the same dimension as the
   Cohere model currently in use.
4. **Operational simplicity**: Ollama's HTTP API requires no API keys, no per-key rate
   limiting, and no credential rotation.

The existing pgvector schema stores 1024-dim vectors. BGE-M3 also emits 1024-dim vectors
for the `bge-m3` model, so no schema migration is required — though a re-ingestion pass
is mandatory because Cohere and BGE-M3 embeddings occupy different semantic spaces and
cannot be mixed.

## Decision

Replace the Cohere embedding integration with a self-hosted Ollama BGE-M3 backend:

- `app/retrieval/embedder.py` is rewritten as a singleton (`EmbedderClient`) that calls
  `POST /api/embeddings` on the configured `OLLAMA_HOST` using `ollama.Client`.
- The singleton is initialised once at import time with double-checked locking to handle
  concurrent startup requests safely.
- `scripts/ingest.py` `generate_embeddings()` calls the same `ollama.Client` directly,
  using `model=OLLAMA_MODEL` (default `bge-m3`).
- `app/retrieval/key_pool.py` is stripped of Cohere-specific key-rotation logic. The
  class is retained as a general-purpose key holder for future API integrations but no
  longer encodes Cohere semantics.
- Configuration: `OLLAMA_HOST` (required, e.g. `https://ollama.cvbooster.es`) and
  `OLLAMA_MODEL` (default `bge-m3`).
- The `cohere` Python package is removed from `requirements.txt`; `ollama` is added and
  pinned.

## Consequences

**Positive:**
- Eliminates recurring Cohere API costs. Embedding is now free at point-of-use given the
  existing Ollama infrastructure.
- The 1024-dim vector schema is unchanged; no Alembic migration is required.
- The `ollama` SDK's HTTP client is simpler than Cohere's batch API; the ingestion code
  is shorter and has fewer failure modes.
- No API key management overhead — one env var (`OLLAMA_HOST`) replaces the key pool.

**Negative / Trade-offs:**
- **Re-ingestion required**: all documents currently in pgvector were embedded with
  Cohere. Cohere and BGE-M3 embeddings are not interchangeable. A full re-ingestion pass
  must complete before semantic search is trustworthy. During the transition window,
  search results degrade silently if old and new vectors coexist.
- **Self-hosted dependency**: availability of `https://ollama.cvbooster.es` is now on the
  critical path for both ingestion and query serving. A Cohere outage previously required
  key rotation; an Ollama outage now requires operator intervention.
- **Model quality difference**: BGE-M3 is a strong multilingual model but has not been
  benchmarked against Cohere `embed-multilingual-v3.0` on the Thermia corpus. A
  retrieval quality regression is possible and should be monitored via the existing
  MRR/recall regression suite.
- **No batching optimisation in this release**: the current implementation embeds one
  chunk at a time. Ollama supports batch embedding; a future optimisation pass could
  improve ingestion throughput.

**Risks:**
- If the Ollama node is unreachable at startup, FastAPI will refuse to start (by design,
  via the lifespan validation). This is a hard failure, not a graceful degradation.
  Operators must ensure `OLLAMA_HOST` is reachable before deploying.
- BGE-M3 model updates on the Ollama node could silently change the embedding space,
  requiring another full re-ingestion. Model pinning at the Ollama server level is
  recommended.
