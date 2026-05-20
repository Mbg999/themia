# Unit Spec: embedder-migration

**Run ID:** `2026-05-20t08-41-48z-bge-m3-migration`
**Layer:** L1 (Provider Swap)

## Purpose

Replace the Cohere embedding client in `embedder.py` with the Ollama Python client for query-time embedding. Eliminate the KeyPool dependency, simplify the module, and add the user-chosen retry strategy. Update dependencies, env vars, and embedder-related tests.

## Responsibilities

- Replace `cohere.Client` with `ollama.Client(host=OLLAMA_HOST)`
- Remove module-level Cohere singletons (`_cohere_client`, `_cohere_client_key`, `_cohere_pool`)
- Remove `get_cohere_pool()` and `_get_client()` functions
- Change `get_query_embedding(text: str) -> list[float]` to use `ollama.embed()`
- Add simple retry: 2 retries with 5s fixed delay (FR-2)
- Read `OLLAMA_HOST` from env (default: `http://localhost:11434`)
- Update `requirements.txt`: add `ollama>=0.6.2`, remove `cohere`
- Update `.env.example`: add `OLLAMA_HOST`, remove Cohere vars
- Rewrite `TestEmbedderKeyPool` for Ollama mocking (6 test cases)
- Update `TestNoRawKeysInLogs` Cohere reference removal

## Public Interfaces

- `embedder.py`: `get_query_embedding(text: str) -> list[float]` (unchanged signature)
- `requirements.txt`: `ollama>=0.6.2` added
- `.env.example`: `OLLAMA_HOST` env var

## Internal Dependencies

- `key-pool-cleanup` — embedder.py no longer imports KeyPool after migration

## External Dependencies

- `ollama` Python package (≥0.6.2) via pip
- `requests` (transitive via ollama client)

## Tasks (from execution plan)

| Task | Description | ACs |
|------|-------------|-----|
| EM-T1 | Rewrite embedder.py with ollama.Client singleton, OLLAMA_HOST env var, retry logic | AC-3, AC-5, AC-7 |
| EM-T2 | Update requirements.txt and .env.example | AC-9 |
| EM-T3 | Rewrite TestEmbedderKeyPool for Ollama mocking | AC-1 |
| EM-T4 | Update test_key_pool.py: TestNoRawKeysInLogs Cohere ref removal | AC-1 |

## Acceptance Criteria

- AC-3: No cohere import in embedder.py (`grep -c "cohere"` == 0)
- AC-5: `ollama` import present in embedder.py
- AC-7: `OLLAMA_HOST` env var configures the endpoint
- AC-9: `ollama>=0.6.2` in requirements.txt
- AC-1: All unit tests pass after changes
- `get_query_embedding(text: str) -> list[float]` returns 1024d vector
- Retry: 2 retries with 5s delay on transient failure

## Definition of Done

- [ ] embedder.py uses ollama.Client, not cohere.Client
- [ ] No Cohere imports remain in embedder.py
- [ ] `OLLAMA_HOST` env var is read and used
- [ ] Retry logic implemented per FR-2
- [ ] requirements.txt updated (ollama add, cohere remove)
- [ ] .env.example updated
- [ ] All embedder tests pass with Ollama mocks
