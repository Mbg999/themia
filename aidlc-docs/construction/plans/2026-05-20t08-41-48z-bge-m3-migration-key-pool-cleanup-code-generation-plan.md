# Code-Generation Plan: key-pool-cleanup

**Run ID:** `2026-05-20t08-41-48z-bge-m3-migration`
**Unit:** `key-pool-cleanup`
**Layer:** L0 (Foundation)
**Plan type:** Standard (requires human approval before code generation starts)
**Author:** code-generator agent, sub-stage 1

---

## Summary

Remove all Cohere-specific code from `KeyPool` before the embedder and ingestion pipelines migrate off Cohere. Only internal references removed — public interfaces (`KeyPool`, `FailureReason`, `classify_failure`, `AllKeysExhaustedError`) remain unchanged. Groq consumers (`llm.py`) unaffected.

Key constraints:
- Groq enum values, classify_failure branches, and cooldowns are **untouched**
- `TestEmbedderKeyPool` and `TestIngestKeyPool` classes are **not** removed in this unit — they reference Cohere at the integration level and will be rewritten by downstream units
- No schema changes, no new endpoints, no frontend work

---

## Files Locked

| File | Role | Action |
|------|------|--------|
| `thermia-back/app/retrieval/key_pool.py` | Primary source | **Modify** — remove Cohere-only references |
| `thermia-back/tests/retrieval/test_key_pool.py` | Primary test | **Modify** — remove Cohere tests, update provider-agnostic tests |

---

## Baseline (before first slice)

Run existing tests to confirm baseline before any changes:
- [x] `pytest thermia-back/tests/retrieval/test_key_pool.py -v` passes

---

## Task Breakdown (TDD order)

### Slice 1 (KP-T1) — Remove Cohere enum, regex, classify_failure branch

**Scope:** Source cleanup of `FailureReason.COHERE_TRIAL_QUOTA`, `_COHERE_TRIAL_RE`, and the Cohere branch in `classify_failure()`. All tests that reference the removed enum value must be updated.

**Files:** `key_pool.py` (modify), `test_key_pool.py` (modify)

**TDD:**
- [x] **Red**: Write a test that asserts `FailureReason` no longer has `COHERE_TRIAL_QUOTA`:
  ```python
  def test_no_cohere_trial_quota_enum(self):
      from app.retrieval.key_pool import FailureReason
      assert not any(m.name == "COHERE_TRIAL_QUOTA" for m in FailureReason)
  ```
  This test **fails** before the change (COHERE_TRIAL_QUOTA still exists).
- [x] **Green**:
  1. Remove `_COHERE_TRIAL_RE = re.compile(...)` from module-level constants in `key_pool.py`
  2. Remove `COHERE_TRIAL_QUOTA = "cohere_trial"` from `FailureReason` enum
  3. Remove the Cohere trial-key branch from `classify_failure()` (lines 63-65, the `if _COHERE_TRIAL_RE.search(text):` block)
  4. Remove `test_cohere_trial_quota` and `test_cohere_trial_key_signal` from `TestClassifyFailure` in `test_key_pool.py`
  5. Update `test_no_raw_keys_in_rotation_logs` (line 346): replace `FailureReason.COHERE_TRIAL_QUOTA` with `FailureReason.GROQ_DAILY_QUOTA` (uses same rotation path; only the label changes)
- [x] **Refactor**: Clean up docstring references that mention "trial key" in `classify_failure`; verify RED test and all remaining tests pass.

**Estimated tokens changed:** ~180 (source) + ~60 (tests) = ~240 total
**Acceptance criteria:** `FailureReason.COHERE_TRIAL_QUOTA` references eliminated from both files; `test_cohere_trial_quota` and `test_cohere_trial_key_signal` removed; RED test passes.

---

### Slice 2 (KP-T2) — Remove Cohere cooldown default

**Scope:** Remove the `"cohere": 2592000` entry from `_DEFAULT_COOLDOWNS`. Update docstrings that reference Cohere.

**Files:** `key_pool.py` (modify)

**TDD:**
- [x] **Red**: Write a test that verifies `_DEFAULT_COOLDOWNS` (via `_get_cooldown_seconds`) has no `"cohere"` specific default:
  ```python
  def test_no_cohere_special_cooldown(self):
      from app.retrieval.key_pool import _get_cooldown_seconds
      import os
      # Without env override, a non-existent provider uses the generic fallback
      cooldown = _get_cooldown_seconds("cohere")
      assert cooldown == 86400  # generic default, not 2592000
  ```
  This test **fails** before the change (cooldown still returns 2592000).
- [x] **Green**: Remove `"cohere": 2592000,  # 30 days ...` from `_DEFAULT_COOLDOWNS` dict.
- [x] **Refactor**:
  1. Update `KeyPool.__init__` docstring: remove "30 d / 1 d" → change to "1 d (daily token reset)"
  2. Update `KeyPool.from_env` docstring: change ```"cohere"`` or ``"groq"``'` to `"groq"` (or any future provider)
  3. Remove "Cohere/Groq" from module docstring → use "Groq"
  4. Update comment at `classify_failure` parameter docstring: remove "Cohere" from example
  5. `grep -ci cohere thermia-back/app/retrieval/key_pool.py` must now return **0**

**Estimated tokens changed:** ~120 (source) = ~120 total
**Acceptance criteria:** AC-4 satisfied (`grep -ci cohere key_pool.py` returns 0); Groq cooldown (86400) untouched; cohere cooldown (2592000) removed.

---

### Slice 3 (KP-T3+KP-T4) — Remove Cohere test references, update provider-agnostic tests

**Scope:** Remove remaining Cohere references from provider-agnostic tests. All tests using `provider="cohere"` string and `COHERE_*` env vars updated to use `"groq"` and `GROQ_*` prefix.

**Files:** `test_key_pool.py` (modify)

**Changed test classes:**
| Class | Changes |
|-------|---------|
| `TestKeyPoolSkeleton` | `provider="cohere"` → `provider="groq"` (3 instances) |
| `TestFromEnv` | `"cohere"` → `"groq"` provider, `COHERE_API_KEYS` → `GROQ_API_KEYS`, `COHERE_API_KEY` → `GROQ_API_KEY` (9 instances) |
| `TestKeyPoolRotation` | `provider="cohere"` → `provider="groq"` (7 instances); log assertion `"provider=cohere"` → `"provider=groq"` |
| `TestNoRawKeysInLogs` | `provider="cohere"` → `provider="groq"`; `COHERE_API_KEY` → `GROQ_API_KEY` (2 instances) |
| `TestFlagResetAfterRecovery` | `provider="cohere"` → `provider="groq"` (1 instance) |
| `TestKeyFormatValidation` | `"cohere"` → `"groq"` provider, `COHERE_API_KEYS` → `GROQ_API_KEYS` (7 instances) |

**Not changed in this unit:**
- `TestEmbedderKeyPool` — Cohere-integration tests; will be removed/rewritten by downstream embedder-migration unit
- `TestIngestKeyPool` — Cohere-integration tests; will be removed/rewritten by downstream ingest-migration unit
- `TestLLMKeyPool` — already Groq-only; no changes needed

**TDD:**
- [x] **Red**: Write a test that asserts no provider-agnostic test function uses `"cohere"` as a provider string:
  ```python
  def test_no_cohere_provider_in_agnostic_tests(self):
      """Verify provider-agnostic tests use 'groq' not 'cohere'."""
      import pathlib
      source = pathlib.Path(__file__).read_text()
      # Check specific test classes for 'provider="cohere"' pattern
      for cls_name in ("TestKeyPoolSkeleton", "TestFromEnv", "TestKeyPoolRotation",
                        "TestNoRawKeysInLogs", "TestFlagResetAfterRecovery",
                        "TestKeyFormatValidation"):
          cls_start = source.find(f"class {cls_name}")
          cls_end = source.find("\n\nclass ", cls_start) if source.find("\n\nclass ", cls_start) > 0 else len(source)
          cls_source = source[cls_start:cls_end]
          assert '"cohere"' not in cls_source, f"{cls_name} still references 'cohere'"
  ```
  This test **fails** before the changes.
- [x] **Green**: Apply all changes listed in the table above.
- [x] **Refactor**: Run full test suite to confirm all tests pass; run RED test again to confirm it passes.

**Estimated tokens changed:** ~380 (tests) = ~380 total
**Acceptance criteria:** AC-1 satisfied (all remaining tests pass); provider-agnostic tests use "groq" not "cohere"; RED test passes.

---

### Slice 4 — Final validation

- [x] **Validate**:
  1. `grep -ci "cohere" thermia-back/app/retrieval/key_pool.py` → **0** (AC-4)
  2. `grep -n "COHERE_TRIAL_QUOTA" thermia-back/tests/retrieval/test_key_pool.py` → **no matches** (only in RED-test assertions verifying absence)
  3. `pytest thermia-back/tests/retrieval/test_key_pool.py -v` → **61 passed** (AC-1)
  4. One-time visual scan of `key_pool.py` and `test_key_pool.py` for any missed Cohere references outside `TestEmbedderKeyPool` and `TestIngestKeyPool`
- [x] **Refactor**: Self-review per `code-review-and-quality` five-axis review

**Estimated tokens:** 0 (verification only)

---

## Verification Plan

| Check | How |
|-------|-----|
| No Cohere in source | `grep -ci'cohere' thermia-back/app/retrieval/key_pool.py` == 0 |
| No COHERE_TRIAL_QUOTA anywhere | `grep -rn 'COHERE_TRIAL_QUOTA' thermia-back/` == 0 |
| Tests pass | `pytest thermia-back/tests/retrieval/test_key_pool.py -v` exit 0 |
| Groq intact | `TestLLMKeyPool` unaffected; Groq enum values and cooldown unchanged |
| TestEmbedderKeyPool/TestIngestKeyPool preserved | Not modified (handled by downstream units) |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Provider-agnostic tests still reference Cohere (just a label string) | Slice 3 explicitly replaces all `"cohere"` strings in provider-agnostic classes |
| Embedder/Ingest tests still reference Cohere but will be removed later | Left intact per spec; downstream units own this |
| Missed docstring reference to Cohere in source | Slice 2 refactor step explicitly updates all docstrings; Slice 4 grep validates |
| KeyPoolRotation modified and log assertions break | Each log assertion updated alongside provider change in Slice 3 |

---

## Definition of Done

- [x] `grep -ci "cohere" thermia-back/app/retrieval/key_pool.py` returns 0
- [x] `grep -rn "COHERE_TRIAL_QUOTA" thermia-back/` returns empty (source code only; .pyc caches excluded)
- [x] All tests pass: `pytest thermia-back/tests/retrieval/test_key_pool.py -v` → 61 passed
- [x] Groq keepers (`TestLLMKeyPool`, `FailureReason.GROQ_DAILY_QUOTA`, groq cooldown) untouched
- [x] `TestEmbedderKeyPool` and `TestIngestKeyPool` preserved (for downstream)
- [x] Self-review (five-axis) completed
