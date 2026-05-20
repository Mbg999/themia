# Unit Spec: ingestion-migration

**Run ID:** `2026-05-20t08-41-48z-bge-m3-migration`
**Layer:** L1 (Provider Swap)

## Purpose

Replace the Cohere embedding call in the ingestion pipeline with Ollama batch embedding. Update the `generate_embeddings()` function signature to remove the KeyPool dependency, and rewrite ingestion tests for Ollama mocking.

## Responsibilities

- Replace `cohere.Client(pool.current()).embed(...)` with `ollama.embed(model='bge-m3', input=batch)`
- Remove Cohere-related imports and constants from ingest.py
- Remove `pool` parameter from `generate_embeddings()` (no KeyPool rotation needed)
- Change `generate_embeddings` to create/reuse an Ollama client internally
- Update `main()` — replace `get_cohere_pool()` with Ollama init
- Apply FR-2 simple retry logic to each batch
- Rewrite `TestCohereEmbedding` and `TestKeyRotation` test classes (5 test cases)

## Public Interfaces

- `scripts/ingest.py`: `generate_embeddings(texts: list[str]) -> list[list[float]]` (signature changed — no `cohere_client` or `pool` params)

## Internal Dependencies

- `key-pool-cleanup` — ingest.py no longer imports KeyPool
- `embedder-migration` (weak dependency) — consistent Ollama client pattern

## External Dependencies

- `ollama` Python package (≥0.6.2) via pip

## Tasks (from execution plan)

| Task | Description | ACs |
|------|-------------|-----|
| IM-T1 | Rewrite generate_embeddings() with ollama.embed(), batch input, retry logic | AC-6, AC-10 |
| IM-T2 | Update main(): remove get_cohere_pool(), init ollama | AC-6 |
| IM-T3 | Rewrite TestCohereEmbedding and TestKeyRotation test classes | AC-1 |

## Acceptance Criteria

- AC-6: `ollama.embed` call present in ingest.py
- AC-10: Embedding dimension remains 1024
- AC-1: All unit tests pass after changes
- Batch embedding sends multiple texts in one `ollama.embed()` call
- Retry: 2 retries with 5s delay on transient failure
- No KeyPool interaction in generate_embeddings

## Definition of Done

- [ ] ingest.py uses `ollama.embed()`, not `cohere.Client.embed()`
- [ ] No `cohere` imports in ingest.py
- [ ] `generate_embeddings` signature has no pool or cohere_client params
- [ ] main() updated to init Ollama instead of Cohere pool
- [ ] All ingestion tests pass with Ollama mocks
