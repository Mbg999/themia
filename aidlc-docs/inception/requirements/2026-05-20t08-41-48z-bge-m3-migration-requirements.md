# Requirements: Cohere → bge-m3 Embedding Migration

**Run ID:** `2026-05-20t08-41-48z-bge-m3-migration`
**Project:** Thermia
**Status:** Complete (Pass 2 — user answers incorporated)
**Date:** 2026-05-20

---

## 1. Intent Analysis

| Attribute | Classification | Rationale |
|-----------|---------------|-----------|
| **Type** | Migration | Replacement of Cohere embedding provider with self-hosted Ollama bge-m3 |
| **Scope** | Multiple Components | embedder.py, ingest.py, key_pool.py, tests (3 source files + 2 test files) |
| **Complexity** | Moderate | Touches embedding client, ingestion pipeline, KeyPool surgery, and test mocks |
| **Clarity** | Clear | User specified migration target (Ollama bge-m3), endpoint URL, model, affected files, and answered all clarifying questions |
| **Depth** | Standard | Moderate complexity, multiple components, brownfield with existing RE artifacts; no depth_override set |

### 1.1 Problem Statement

The current embedding system uses **Cohere embed-multilingual-v3.0** via the `cohere` Python SDK. This incurs ongoing per-embedding API costs and requires KeyPool-managed API key rotation for rate-limit handling. The Cohere provider code is tightly coupled into embedder.py (query-time), ingest.py (ingestion-time), and key_pool.py (shared KeyPool).

The goal is to migrate to a self-hosted **Ollama instance serving bge-m3** at `https://ollama.cvbooster.es`, eliminating Cohere costs and simplifying the embedding architecture by removing the key-management machinery for embeddings.

### 1.2 Drivers

1. **Cost reduction** — Eliminate Cohere per-embedding API fees (primary driver per user).
2. **Operational simplification** — Remove KeyPool dependency for embeddings; simplify error handling; eliminate rate-limit/rotation complexity.
3. **Self-hosted control** — Ollama endpoint is within the existing infrastructure (cvbooster.es domain).

---

## 2. User Decisions (from Clarifying Questions)

The following decisions were collected from the Pass 1 question-answer cycle and are binding on the implementation:

### Q1: Primary Success Metric
> **Answer: C** — Both cost reduction AND ops simplification are equally important.

This means the migration is not considered successful until:
- Cohere API costs are zeroed out (no Cohere calls happen in normal operation).
- KeyPool Cohere code is removed (not just bypassed).
- Error handling is simpler than the current retry-with-rotation strategy.

### Q2: Ollama Error Handling
> **Answer: B** — Simple retry: 2 retries with fixed 5s delay, then raise.

| Detail | Value |
|--------|-------|
| Max retries | 2 |
| Delay between retries | 5 seconds (fixed) |
| On exhaustion | Re-raise last exception |
| Key rotation | Not applicable (no API keys for self-hosted Ollama) |
| Failure classification | Not needed (no rotation decisions to make) |

### Q3: HTTP Client and Connection
> **Answer: X** — Use the official `ollama` Python client library: https://github.com/ollama/ollama-python

| Detail | Value |
|--------|-------|
| Library | `ollama` (pip install ollama) |
| Version | ≥ 0.6.2 |
| API function | `ollama.embed(model='bge-m3', input=...)` |
| Client constructor | `ollama.Client(host=...)` |
| Host config | `OLLAMA_HOST` env variable (default: `http://localhost:11434`) |
| Production value | `https://ollama.cvbooster.es` |
| Auth | None (self-hosted; remove API-key code from embedder) |

The `ollama` client supports both single and batch embedding via the same `ollama.embed()` function — passing a list of strings returns embeddings for all inputs in one call.

### Q4: KeyPool Simplification
> **Answer: A** — Remove Cohere-related code from KeyPool entirely; keep Groq key management unchanged.

Scope of KeyPool changes:
- Remove `FailureReason.COHERE_TRIAL_QUOTA` enum member.
- Remove `_COHERE_TRIAL_RE` regex pattern.
- Remove Cohere-specific check in `classify_failure()` (the `_COHERE_TRIAL_RE` branch).
- Remove `"cohere"` from `_DEFAULT_COOLDOWNS` dict.
- Keep Groq `FailureReason.GROQ_DAILY_QUOTA`, `_GROQ_DAILY_RE`, Groq classify_failure branch, and Groq default cool-down.
- Keep all KeyPool infrastructure (pool rotation, cool-down, logging) intact for Groq.
- The embedder module no longer imports or uses `KeyPool`, `AllKeysExhaustedError`, or `classify_failure`.

### Q5: Ingestion Batching
> **Answer: X** — Use `ollama.embed(model='bge-m3', input=[...])` with batch input; if batching is supported (it is — see verification below), use it; otherwise fall back to sequential with throttling (Option B).

**Verification:** The Ollama Embeddings API documentation confirms batch input is supported:
```python
batch = ollama.embed(
  model='bge-m3',
  input=[
    'First text',
    'Second text',
    'Third text',
  ]
)
print(len(batch['embeddings']))  # number of vectors
```

**Decision:** Use batch embedding with a configurable batch size. The existing Cohere batch size of 50 is a reasonable default. Since Ollama is self-hosted with no rate limits, no inter-batch sleep is needed. However, to avoid overwhelming the Ollama server, a configurable delay (`EMBED_INTER_BATCH_SLEEP`, default `0.0`) is preserved as an optional parameter.

### Q6: Latency and Performance
> **Answer: A** — Embedding latency is not critical; same user experience as before is acceptable.

No latency SLA. The bottleneck is typically the subsequent LLM call to Groq. No performance tuning required beyond the simple retry configuration.

### Q7: Migration Scope Boundaries
> **Answer: F** — Strictly a provider swap; no other changes.

**Explicitly out of scope:**
- Changing the vector dimension (must stay 1024d — bge-m3 default).
- Changing the database schema or pgvector index (ivfflat, cosine_ops, lists=50).
- Modifying searcher.py, fusion.py, context_builder.py, or llm.py.
- Introducing a new embedding abstraction layer / interface.
- Re-ingesting existing documents (existing embeddings remain valid; they coexist with bge-m3 vectors in the same 1024-d space).

**Known limitation:** Query embeddings generated by bge-m3 will be in a different embedding space than the existing Cohere document embeddings. Since no re-ingestion is planned, search quality for pre-existing documents may differ from current results. This is accepted by the user. Vector dimension (1024) is compatible — no schema change needed.

### Q8: Verification and Rollback
> **Answer: A** — All unit tests pass with new mocks; manual endpoint test confirms same-quality results; rollback = revert commit + keep old Cohere keys.

| Detail | Value |
|--------|-------|
| Primary verification | All unit tests pass |
| Secondary verification | Manual POST /analyze test returns valid response |
| Rollback strategy | `git revert` the migration commit |
| Cohere environment variables | Retained in .env during rollback window |
| Rollback window | Keep Cohere keys active for at least one release cycle |

---

## 3. Functional Requirements

### FR-1: Embedder — Replace Cohere client with Ollama client

**File:** `thermia-back/app/retrieval/embedder.py`

- Replace `cohere.Client` with `ollama.Client` (or use module-level `ollama.embed()`).
- Remove all `cohere` imports.
- Remove module-level singletons: `_cohere_client`, `_cohere_client_key`, `_cohere_pool`.
- Remove `get_cohere_pool()` function.
- Remove `_get_client()` function.
- Change `get_query_embedding(text: str) -> list[float]` to use `ollama.embed()`.
- Model: `"bge-m3"` (1024 dimensions).
- No `input_type` parameter (bge-m3 has no query/document distinction).
- Return `list[float]` — same interface as before; callers (searcher.py) need no changes.
- Query the `OLLAMA_HOST` env variable (via `os.environ.get("OLLAMA_HOST", "http://localhost:11434")`).

### FR-2: Embedder — Simple retry on failure

**Applies to:** `get_query_embedding()` in embedder.py and `generate_embeddings()` in ingest.py

- 2 retries with 5s fixed delay between retries (user decision Q2).
- On success within retry budget → return result normally.
- On exhaustion → re-raise the last exception.
- No API key rotation logic.
- No failure classification.
- No KeyPool interaction.

```python
_RETRY_COUNT = 2
_RETRY_DELAY_SECONDS = 5
```

### FR-3: Embedder — Ollama client configuration

- Read `OLLAMA_HOST` from environment (default: `http://localhost:11434`).
- Create `ollama.Client(host=ollama_host)` for query-time embedding.
- The client can be a module-level singleton (no key rotation means no need to rebuild).

### FR-4: KeyPool — Remove Cohere-specific code

**File:** `thermia-back/app/retrieval/key_pool.py`

Changes:

| Element | Action |
|---------|--------|
| `FailureReason.COHERE_TRIAL_QUOTA` | Remove enum member |
| `_COHERE_TRIAL_RE` regex | Remove regex pattern |
| `classify_failure()` — Cohere branch | Remove `_COHERE_TRIAL_RE` check |
| `_DEFAULT_COOLDOWNS["cohere"]` | Remove "cohere" entry (keep "groq": 86400) |
| `classify_failure()` — generic RATE_LIMIT_429 | Keep (still relevant for Groq) |
| `classify_failure()` — PERSISTENT_5XX | Keep |
| `classify_failure()` — GROQ_DAILY_QUOTA | Keep |
| `KeyPool` constructor | Keep (provider-agnostic) |
| `from_env("groq")` | Keep |
| All rotation/logging/cool-down logic | Keep (still used by Groq) |

### FR-5: Ingest Pipeline — Replace Cohere embed call

**File:** `thermia-back/scripts/ingest.py`

- Replace `cohere.Client(pool.current()).embed(...)` with `ollama.embed(model='bge-m3', input=batch)`.
- Remove Cohere-related imports and constants:
  - `_EMBED_RETRY_DELAYS` (replaced by FR-2 retry logic).
  - `_EMBED_INTER_BATCH_SLEEP` env var (set default to 0.0; keep as optional).
  - `_EMBED_BATCH_SIZE` (keep as a batching parameter for ingestion, rename if desired).
- Remove `pool` parameter from `generate_embeddings()` (no KeyPool rotation needed).
- Change `generate_embeddings` signature to not require a `cohere_client` argument. Instead, the function creates or reuses an `ollama` client internally.
- Use `ollama.embed(model='bge-m3', input=batch)` for batch embedding.
- Remove `from app.retrieval.embedder import get_cohere_pool` from `main()`.
- Remove `cohere` import from `main()`.
- Apply FR-2 simple retry logic to each batch.

### FR-6: Ingest Pipeline — Update main() for Ollama

- Replace `pool = get_cohere_pool()` with Ollama client initialization.
- Replace `generate_embeddings(cohere.Client(pool.current()), embed_texts, pool=pool)` with `generate_embeddings(embed_texts)`.
- Remove Cohere API key references from the module docstring.

### FR-7: Configuration — Environment Variables

**New variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL (for production: `https://ollama.cvbooster.es`) |

**Removed variables:**

| Variable | Reason |
|----------|--------|
| `COHERE_API_KEYS` / `COHERE_API_KEY` | No longer needed — Ollama is self-hosted, no API key |
| `COHERE_KEY_COOLDOWN_SECONDS` | Cohere KeyPool code removed |
| `EMBED_INTER_BATCH_SLEEP` | No rate limits on self-hosted Ollama (optional — keep as `0.0` default if kept) |

### FR-8: Dependencies — Add ollama, evaluate cohere removal

**File:** `thermia-back/requirements.txt`

- Add `ollama>=0.6.2`.
- Remove `cohere` if the only consumers were embedder.py and ingest.py (verify: `grep -r "import cohere" thermia-back/` should only hit embedder.py and ingest.py after KeyPool changes).
- `cohere` is not used by the Groq LLM path (which uses `langchain_groq`).

---

## 4. Non-Functional Requirements

### NFR-1: Cost
- No ongoing per-embedding API costs. Ollama runs on existing infrastructure (cvbooster.es).
- The only cost is the compute/energy for running the Ollama server (already provisioned).

### NFR-2: Latency
- No explicit latency SLA (user decision Q6 — "same UX as before is acceptable").
- Query-time embedding latency depends on Ollama server response time.
- Ingestion throughput depends on Ollama batch embedding performance.
- The 5s retry delay is acceptable for transient failures.

### NFR-3: Error Handling
- **Transient failures** (network timeout, connection reset): 2 retries with 5s delay, then re-raise.
- **Ollama server errors** (500, 503): treated as transient; retried per FR-2.
- **Invalid input errors** (400): re-raise immediately (no retry).
- **Client configuration errors** (wrong host, connection refused): re-raise after retry budget.
- Error messages should indicate "Ollama embedding failed" (not "Cohere") in logs.

### NFR-4: Maintainability
- **Dead code elimination:** No Cohere dead code left in embedder or key_pool.
- **Simplified embedder:** No KeyPool singleton, no failure classification, no key rotation logic, no `_get_client()` machinery. A single `ollama.Client(host=...)` at module level.
- **Intact Groq:** KeyPool module stays functional for Groq; only Cohere references removed.
- **Configuration surface:** Reduced from 5+ Cohere env vars to 1 Ollama env var.

### NFR-5: Backward Compatibility
- **Interface stability:** `get_query_embedding(text: str) -> list[float]` signature unchanged.
- **Vector dimension:** 1024d unchanged (bge-m3 default); no schema migration needed.
- **pgvector index:** No rebuild needed (ivfflat index is dimension-agnostic within 1024).
- **Existing embeddings:** Not invalidated; coexist with bge-m3 embeddings in the same vector column.
- **Rollback:** Git revert restores previous functionality; Cohere env vars still present.

**Known backward-compatibility gap:** Query embeddings from bge-m3 exist in a different embedding space than Cohere-generated document embeddings. This means cosine-similarity comparisons between bge-m3 queries and Cohere-embedded documents may be suboptimal. The user has accepted this trade-off (Q7 — no re-ingestion).

### NFR-6: Rollback Strategy
- **Primary rollback:** `git revert` the migration commit(s).
- **Cohere keys:** Remain in `.env`; no cleanup of Cohere env vars during migration (user decision Q8).
- **Validation before rollback:** Run full test suite; if tests fail, rollback immediately.
- **Rollback window:** At least one release cycle (keep Cohere keys until next deployment confirms stability).

---

## 5. Acceptance Criteria

| ID | Criterion | How to Verify |
|----|-----------|---------------|
| AC-1 | All existing unit tests pass with updated mocks | `pytest thermia-back/tests/ -v` — all tests pass (embedder tests updated; key_pool Cohere tests removed; ingest tests updated) |
| AC-2 | `POST /analyze` returns a valid response | Manual test: POST a Spanish legal PDF to `/analyze`, verify 200 response with `resumen`, `implicaciones_legales`, `fundamento_juridico` |
| AC-3 | No Cohere import in embedder.py | `grep -c "cohere" thermia-back/app/retrieval/embedder.py` == 0 |
| AC-4 | No Cohere reference in key_pool.py | `grep -c "cohere" thermia-back/app/retrieval/key_pool.py` == 0 (case-insensitive) |
| AC-5 | Ollama client used in embedder.py | `grep "ollama" thermia-back/app/retrieval/embedder.py` — contains `import ollama` or `from ollama import` |
| AC-6 | Ollama client used in ingest.py | `grep "ollama" thermia-back/scripts/ingest.py` — contains `ollama.embed` call |
| AC-7 | `OLLAMA_HOST` env var configures the endpoint | Test: set `OLLAMA_HOST=http://test-host:11434`, verify `ollama.Client` constructed with this host |
| AC-8 | Rollback restores Cohere functionality | `git revert` migration commits → restore old embedder.py/ingest.py → tests pass with Cohere mocks |
| AC-9 | `ollama>=0.6.2` in requirements.txt | `grep "ollama" thermia-back/requirements.txt` — entry exists |
| AC-10 | Embedding dimension remains 1024 | Manual check: `ollama.embed(model='bge-m3', input='test')['embeddings'][0]` has length 1024 |

---

## 6. Testing Strategy

### 6.1 Test File Inventory

| Test File | Impact | Action |
|-----------|--------|--------|
| `thermia-back/tests/retrieval/test_key_pool.py` | High — `TestEmbedderKeyPool` tests mock Cohere | Rewrite `TestEmbedderKeyPool` to mock `ollama`; test retry logic instead of key rotation |
| `thermia-back/tests/retrieval/test_key_pool.py` | Medium — `TestClassifyFailure`, `TestKeyPoolRotation` | Remove Cohere-specific test cases (`test_cohere_trial_quota`, `test_cohere_trial_key_signal`); keep provider-agnostic and Groq tests |
| `thermia-back/tests/retrieval/test_key_pool.py` | Medium — `TestFromEnv` | Remove or re-target Cohere-specific parametrization; keep Groq tests and provider-agnostic tests |
| `thermia-back/tests/retrieval/test_key_pool.py` | Low — `TestNoRawKeysInLogs` | Update `test_no_raw_keys_in_rotation_logs` to not reference `FailureReason.COHERE_TRIAL_QUOTA`; replace with `FailureReason.RATE_LIMIT_429` |
| `thermia-back/tests/test_ingestion.py` | High — `TestCohereEmbedding`, `TestKeyRotation` | Rewrite to test `ollama.embed` invocation instead of `cohere.Client.embed`; remove key rotation tests |
| `thermia-back/tests/test_retrieval.py` | None | These tests test searcher, fusion, context_builder — no embedder dependency |

### 6.2 Embedder Test Plan

The `TestEmbedderKeyPool` class (in `tests/retrieval/test_key_pool.py`, line 385) must be rewritten with these test cases:

| Test | Description | Expected |
|------|-------------|----------|
| `test_query_embedding_uses_ollama` | `get_query_embedding` calls `ollama.embed` with `model='bge-m3'` | `ollama.embed` called once with correct args |
| `test_returns_1024d_vector` | Result is a list of 1024 floats | `len(result) == 1024` |
| `test_retries_on_failure` | After transient failure, retries 2 times with 5s delay | 3 total attempts (1 original + 2 retries) |
| `test_raises_after_retry_exhaustion` | If all 3 attempts fail, re-raises the last exception | Exception propagates |
| `test_non_transient_error_raises_immediately` | Non-retryable errors (e.g., connection refused) may still be retried based on exception type; verify behavior | Exception propagates after retries |
| `test_ollama_host_from_env` | `OLLAMA_HOST` env var controls the endpoint | Client constructed with correct host |

### 6.3 Ingestion Test Plan

The `TestCohereEmbedding` and `TestKeyRotation` classes in `tests/test_ingestion.py` must be rewritten:

| Test | Description | Expected |
|------|-------------|----------|
| `test_embed_called_with_bge_m3` | `generate_embeddings` calls `ollama.embed` with `model='bge-m3'` | Correct model parameter |
| `test_batch_embedding` | Sends multiple texts in one call to `ollama.embed` | Single call with list input; correct number of vectors returned |
| `test_retry_on_transient_failure` | Transient failure triggers 2 retries with 5s delay | Retry count correct; eventual success returns embeddings |
| `test_all_retries_exhausted` | After retry budget exhausted, exception propagates | Final exception raised |
| `test_no_key_rotation` | No KeyPool or `mark_failed` call | Zero KeyPool interactions |

### 6.4 KeyPool Test Adjustments

- Remove `test_cohere_trial_quota` and `test_cohere_trial_key_signal` from `TestClassifyFailure`.
- Update `TestKeyPoolRotation`: switch provider from `"cohere"` to `"groq"` or a generic provider name like `"test"` (the tests are provider-agnostic).
- Update `TestFromEnv`: switch Cohere test data to Groq or generic; keep Groq-specific test.
- Update `TestNoRawKeysInLogs`: replace `FailureReason.COHERE_TRIAL_QUOTA` with another reason for the 2-key exhaustion test.

---

## 7. Implementation Boundaries

### Always Do
- Use `ollama` Python client for all Ollama interactions.
- Maintain 1024-dimension embeddings (bge-m3 default).
- Keep `get_query_embedding(text: str) -> list[float]` interface unchanged.
- Remove Cohere dead code (imports, singletons, env vars, KeyPool branches).
- Keep Groq KeyPool functionality fully intact.
- Update all mock-based tests to mock `ollama` instead of `cohere`.
- Verify `cohere` can be removed from `requirements.txt` (check no remaining imports).

### Ask First
- Changing the ingestion batch size from 50.
- Adding new Ollama-specific configuration beyond `OLLAMA_HOST`.
- Adding an embedding quality comparison test.
- Re-ingesting existing documents (user explicitly said no — Q7).
- Changing the retry strategy from the user-chosen simple retry (Q2).

### Never Do
- Modify searcher.py, fusion.py, context_builder.py, or llm.py.
- Change the database schema or pgvector index (vector(1024), ivfflat, cosine_ops).
- Remove or modify Groq key management in key_pool.py.
- Introduce a new embedding abstraction layer / interface.
- Re-ingest existing documents without explicit user approval.
- Remove Cohere env vars from `.env` files (keep them for rollback window per Q8).

---

## 8. Open Questions (Resolved)

All 8 clarifying questions have been answered. No unresolved questions remain for implementation.

| ID | Question | Answer |
|----|----------|--------|
| Q1 | Primary success metric | C — Both cost reduction AND ops simplification |
| Q2 | Error handling strategy | B — Simple retry: 2x, 5s delay |
| Q3 | HTTP client library | X — Ollama Python client |
| Q4 | KeyPool simplification | A — Remove Cohere, keep Groq |
| Q5 | Ingestion batching | X — Use `ollama.embed` batch input |
| Q6 | Latency expectations | A — Not critical |
| Q7 | Scope boundaries | F — Strictly provider swap |
| Q8 | Verification and rollback | A — Tests + manual; revert to rollback |
