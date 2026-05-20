# Build & Test Summary — key-pool-cleanup

## Run Metadata
| Field | Value |
|-------|-------|
| Run ID | `2026-05-20t08-41-48z-bge-m3-migration` |
| Unit | `key-pool-cleanup` |
| Sub-stage | `build-test` |
| Executed | 2026-05-20 |

## Test Results

### Overall
| Metric | Count |
|--------|-------|
| Total tests | 61 |
| Passed | 57 |
| Failed | 4 |
| Coverage | Not measured (no coverage config) |

### Test Class Breakdown
| Test Class | Result | Count |
|-----------|--------|-------|
| `TestKeyPoolSkeleton` | ✅ All passed | 4 |
| `TestFromEnv` | ✅ All passed | 8 |
| `TestClassifyFailure` | ✅ All passed | 10 |
| `TestKeyPoolRotation` | ✅ All passed | 12 |
| `TestNoRawKeysInLogs` | ✅ All passed | 2 |
| `TestEmbedderKeyPool` | ✅ All passed | 3 |
| **`TestLLMKeyPool`** | ❌ **4 failed** | 4 |
| `TestIngestKeyPool` | ✅ All passed | 2 |
| `TestClassifyFailureFalsePositives` | ✅ All passed | 4 |
| `TestFlagResetAfterRecovery` | ✅ All passed | 1 |
| `TestKeyFormatValidation` | ✅ All passed | 5 |
| Red-test helpers (`test_no_cohere_*`) | ✅ All passed | 3 |

### Failed Tests — Root Cause Analysis

#### 1. `test_llm_uses_active_groq_key` — `KeyError: 'key'`
- **Symptom**: `captured_api_key["key"]` raised KeyError — the mock ChatGroq was never called.
- **Root cause**: `analyze_with_llm("context text", "query text")` calls `_is_valid_retrieval("context text")` first. "context text" does not contain legal keywords (`ley`, `artículo`, `código`, etc.), so the function returns the "INSUFICIENCIA DE BASE NORMATIVA EN EL CONTEXTO" early-return dict. The Groq pool and ChatGroq mock are never reached.
- **Fix needed**: Update test context string to include a legal keyword, e.g., `"La ley establece..."` or mock/patch `_is_valid_retrieval`.

#### 2. `test_groq_daily_quota_rotates_and_retries` — `AssertionError: 'INSUFICIENCIA DE BASE NORMATIVA EN EL CONTEXTO' != 'ok'`
- **Symptom**: Got the INSUFICIENCIA string instead of "ok".
- **Root cause**: Same as above — `_is_valid_retrieval("ctx")` returns `False` (context too short, no legal keywords).
- **Fix needed**: Update test to pass context that passes the validation gate.

#### 3. `test_all_groq_keys_exhausted_propagates` — `DID NOT RAISE AllKeysExhaustedError`
- **Symptom**: The expected exception was never raised.
- **Root cause**: Same early-return path — `_is_valid_retrieval("ctx")` returns `False`, so the function returns the INSUFICIENCIA dict before ever invoking ChatGroq.
- **Fix needed**: Update test context to pass validation.

#### 4. `test_non_rotating_llm_failure_reraises` — `DID NOT RAISE Exception`
- **Symptom**: The expected 400 exception was never raised.
- **Root cause**: Same as above.
- **Fix needed**: Update test context to pass validation.

### Summary Finding
The `_is_valid_retrieval()` validation gate was introduced in `llm.py` (part of this migration layer) but the existing `TestLLMKeyPool` tests were not updated to use context strings that pass the gate. These tests send short/no-context strings like `"context text"` or `"ctx"` that contain no legal keywords, triggering the early-return path and never reaching the mocked Groq invocation.

## Cohere Cleanup Verification

### Source file (`key_pool.py`)
```
grep -ci "cohere" key_pool.py → 0  ✅
```
All Cohere references have been successfully removed from the source file.

### Test file (`test_key_pool.py`)
```
grep -ci "cohere" test_key_pool.py → 38  ✅ (expected)
```
The remaining 38 Cohere references are confined to:
- `TestEmbedderKeyPool` (3 tests) — Cohere-based embedder tests (preserved)
- `TestIngestKeyPool` (2 tests) — Cohere pool wiring tests (preserved)
- `test_no_cohere_*` (3 tests) — red-test helpers that verify cleanup (preserved)

All 3 cleanup-verification red tests pass:
- `test_no_cohere_trial_quota_enum` ✅
- `test_no_cohere_special_cooldown` ✅  
- `test_no_cohere_provider_in_agnostic_tests` ✅

## Recommendation
**blocked** — 4 test regressions in `TestLLMKeyPool`. The fix is in the test file, not production code:
Update the 4 failing tests to pass context strings that satisfy `_is_valid_retrieval()`, e.g., changing `"context text"` to `"La ley establece el contexto legal"` or similar legal-content text.

## Approval Gate
Status: `needs_human` — awaiting review of test failures before proceeding to next unit.
