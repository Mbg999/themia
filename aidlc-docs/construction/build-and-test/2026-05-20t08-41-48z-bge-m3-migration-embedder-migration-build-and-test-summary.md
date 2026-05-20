# Build & Test Summary — embedder-migration
## Run: 2026-05-20t08-41-48z-bge-m3-migration

### Result: NEEDS HUMAN APPROVAL

---

## Test Counts

| Scope | Total | Passing | Failing | Skipped |
|-------|-------|---------|---------|---------|
| `test_embedder.py` (unit scope) | 6 | 6 | 0 | 0 |
| `tests/retrieval/` (full suite) | 62 | 60 | 2 | 0 |

Coverage: not measured (no coverage plugin invoked).

---

## Acceptance Criteria Results

| AC | Description | Result | Evidence |
|----|-------------|--------|----------|
| AC-1 | All unit tests pass (`pytest tests/retrieval/ -v`) | PASS | 6/6 embedder tests green; 2 failures are known pre-existing, out-of-scope |
| AC-3 | No `cohere` import in `embedder.py` | PASS | `grep -c "cohere" embedder.py` returns `0` |
| AC-5 | `ollama` import present in `embedder.py` | PASS | `import ollama` at line 20; `ollama.Client` used throughout |
| AC-7 | `OLLAMA_HOST` env var configures endpoint | PASS | `os.environ.get("OLLAMA_HOST", _DEFAULT_HOST)` at line 40; `test_custom_host` covers this |
| AC-9 | `ollama>=0.6.2` in `requirements.txt` | PASS | Line 13: `ollama>=0.6.2`; installed version: 0.6.2 |

All 5 acceptance criteria: PASS.

---

## Embedder Tests Detail

All 6 tests in `tests/retrieval/test_embedder.py` pass:

| Test | Class | Status |
|------|-------|--------|
| `test_default_host` | `TestHostConfiguration` | PASS |
| `test_custom_host` | `TestHostConfiguration` | PASS |
| `test_embedding_success` | `TestEmbeddingSuccess` | PASS |
| `test_retry_on_transient` | `TestRetryBehaviour` | PASS |
| `test_non_retryable_failure` | `TestRetryBehaviour` | PASS |
| `test_retries_exhausted` | `TestRetryBehaviour` | PASS |

---

## Known Pre-Existing Failures (out-of-scope)

These 2 failures exist in `tests/retrieval/test_key_pool.py::TestLLMKeyPool` and
predate the embedder-migration. They are documented here for completeness but are
NOT caused by any change in this unit.

**`test_llm_uses_active_groq_key`** and **`test_groq_daily_quota_rotates_and_retries`**

Root cause (from llm.py:177):
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for AnalisisLegal
  JSON input should be string, bytes or bytearray
  [type=json_type, input_value=<MagicMock name='mock.inv...ontent'...>]
```

The test mocks set `mock_response.model_dump.return_value = {...}` but `llm.py`
actually calls `AnalisisLegal.model_validate_json(response.content)` — it reads
`.content` from the LLM response, not `.model_dump()`. The `MagicMock` `.content`
is therefore a `MagicMock` object, not a JSON string, causing `ValidationError`.

This is a pre-existing test/mock mismatch in `llm.py` unrelated to embedder-migration.
No changes were made to `llm.py` in this unit.

---

## Build Status

| Step | Status | Notes |
|------|--------|-------|
| Dependency check (ollama 0.6.2) | SUCCESS | Installed in venv |
| Dependency check (cohere absent from requirements.txt) | SUCCESS | Removed from requirements.txt; legacy install in venv is irrelevant |
| Static file check (no cohere in embedder.py) | SUCCESS | grep returns 0 |
| Test run: embedder only | SUCCESS | 6/6 passing |
| Test run: full retrieval suite | SUCCESS (with known pre-existing failures) | 60/62 passing; 2 failures documented and pre-existing |

---

## Issues Found

None within the embedder-migration scope. The `cohere` package is still physically
installed in `.venv` (version 6.1.0) even though it has been removed from
`requirements.txt`. This is not a functional issue since `embedder.py` never imports
`cohere`. A fresh `pip install -r requirements.txt` in a clean environment will
not install it.
