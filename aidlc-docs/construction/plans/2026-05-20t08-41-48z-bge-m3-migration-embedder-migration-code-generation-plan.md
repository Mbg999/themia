# Code Generation Plan: embedder-migration

**Run ID:** `2026-05-20t08-41-48z-bge-m3-migration`
**Unit:** embedder-migration
**Sub-stage:** plan

## Overview

Replace Cohere embedding client with Ollama Python client in `embedder.py`.
- Remove KeyPool dependency from embedder (standalone singleton pattern)
- `ollama.Client(host=OLLAMA_HOST).embed(model='bge-m3', input=texts)`
- Simple retry: 2 retries, fixed 5s delay (FR-2)
- OLLAMA_HOST env var (default: `http://localhost:11434`)
- Update config files (requirements.txt, .env.example)
- Clean up Cohere refs in test_key_pool.py

---

## TDD Slice 1 — Core embedder rewrite: tests + implementation (EM-T3 + EM-T1)

### ACs covered: AC-3 (no cohere import), AC-5 (ollama import), AC-7 (OLLAMA_HOST), AC-1 (tests pass)

**Description:** Write the 6 test cases for the new Ollama-based embedder in a dedicated
`test_embedder.py` file. Then implement the new `embedder.py` to make them pass.

**Files:**
- `thermia-back/tests/retrieval/test_embedder.py` (new)
- `thermia-back/app/retrieval/embedder.py` (rewrite)

### Test cases (Red)

| # | Test | Assertion |
|---|------|-----------|
| 1 | `test_default_host` | `OLLAMA_HOST` absent → `ollama.Client(host="http://localhost:11434")` |
| 2 | `test_custom_host` | `OLLAMA_HOST` set → uses that host |
| 3 | `test_embedding_success` | Returns 1024-dim vector with correct values |
| 4 | `test_retry_on_transient` | 2 retries, 5s delay → eventually succeeds |
| 5 | `test_non_retryable_failure` | Non-retryable errors raise immediately (no retry) |
| 6 | `test_retries_exhausted` | After 2 retries still failing → raises |

**Mocking strategy:** `monkeypatch.setenv` for OLLAMA_HOST; `unittest.mock.patch("app.retrieval.embedder.ollama")`
to mock `ollama.Client` and its `.embed()` method. The mock `embed()` returns `{"embeddings": [[0.1]*1024]}`.

### Implementation (Green)

New `embedder.py`:
- Remove `cohere` import, `_cohere_client`, `_cohere_client_key`, `_cohere_pool`
- Remove `get_cohere_pool()`, `_get_client()`
- Add `import ollama`
- Add `_ollama_client: ollama.Client | None = None` singleton
- Add `_get_ollama_client() -> ollama.Client` that reads `OLLAMA_HOST` (default `http://localhost:11434`)
- New `get_query_embedding(text: str) -> list[float]`:
  - Delegate to client helper; 2 retries with `time.sleep(5)` between attempts
  - Non-retryable = `ollama.ResponseError` with status 4xx → re-raise immediately
  - Transient = connection errors, 5xx, or unexpected exceptions → retry
- Thread-safety: `_ollama_client` only written inside `_get_ollama_client()`

**Refactor:** Verify no dead imports, ensure `__all__` or docstring updated.

**Check:**
- [x] `get_query_embedding(text: str) -> list[float]` returns 1024d vector
- [x] No `cohere` import in embedder.py (`grep -c "cohere"` == 0)
- [x] `ollama` import present
- [x] `OLLAMA_HOST` env var configures endpoint
- [x] 2 retries with 5s delay on transient failure
- [x] Non-retryable (4xx) re-raises immediately
- [x] Singleton client — rebuilt only when host changes

---

## TDD Slice 2 — Config file updates (EM-T2)

### ACs covered: AC-9 (ollama>=0.6.2 in requirements.txt)

**Files:**
- `thermia-back/requirements.txt`
- `thermia-back/.env.example`

### Changes

| File | Action |
|------|--------|
| `requirements.txt` | Remove `cohere>=5.0.0` line; add `ollama>=0.6.2` |
| `.env.example` | Add `OLLAMA_HOST=http://localhost:11434`; remove Cohere block (lines 22–39) |

**Check:**
- [x] `ollama>=0.6.2` in requirements.txt
- [x] `cohere` NOT in requirements.txt
- [x] `.env.example` has `OLLAMA_HOST`
- [x] `.env.example` has no `COHERE_` variables

---

## TDD Slice 3 — Cohere ref cleanup in test_key_pool.py (EM-T4)

### ACs covered: AC-1 (all unit tests pass)

**Files:**
- `thermia-back/tests/retrieval/test_key_pool.py`

### Changes

| Item | Action | Reason |
|------|--------|--------|
| `TestEmbedderKeyPool` class (lines 373–468) | **Remove entirely** | Tests Cohere+KeyPool integration — replaced by new `test_embedder.py` |
| `test_no_cohere_trial_quota_enum()` (lines 773–776) | **Remove** | COHERE_TRIAL_QUOTA already removed from FailureReason; no longer needed |
| `test_no_cohere_special_cooldown()` (lines 779–783) | **Remove** | Cohere-specific cooldown check no longer relevant |
| `test_no_cohere_provider_in_agnostic_tests()` (lines 786–801) | **Keep** | Still valid — guards against 'cohere' leaking into provider-agnostic tests |
| `TestIngestKeyPool` (lines 606–653) | **Keep** | Tests ingest.py, not embedder.py — separate concern |

**Check:**
- [x] No `COHERE_TRIAL_QUOTA` references in test files
- [x] No `TestEmbedderKeyPool` in test_key_pool.py
- [x] All tests in `test_key_pool.py` pass unchanged
- [x] No cohere_test utility functions orphaned

---

## Execution order

| Step | Action | Slice |
|------|--------|-------|
| 1 | **Red** — Write `test_embedder.py` with 6 failing tests | Slice 1 |
| 2 | **Green** — Rewrite `embedder.py` to pass all 6 tests | Slice 1 |
| 3 | **Refactor** — Clean up embedder.py, update docstring | Slice 1 |
| 4 | **Validate** — `python -m pytest thermia-back/tests/retrieval/test_embedder.py -v` | Slice 1 |
| 5 | **Green** — Update `requirements.txt` and `.env.example` | Slice 2 |
| 6 | **Validate** — Run full test suite, check no regressions | Slice 2 |
| 7 | **Green** — Remove Cohere refs from `test_key_pool.py` | Slice 3 |
| 8 | **Validate** — `python -m pytest thermia-back/tests/retrieval/ -v` | Slice 3 |
| 9 | **Self-review** — Five-axis code review | All |

---

## Plan Approval

- [x] Slice 1: Core embedder rewrite (tests + impl)
- [x] Slice 2: Config file updates
- [x] Slice 3: Cohere ref cleanup in test_key_pool.py
- [x] Self-review and final validation

---

*Generated by code-generator subagent — plan stage*
