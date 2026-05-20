# Unit Spec: key-pool-cleanup

**Run ID:** `2026-05-20t08-41-48z-bge-m3-migration`
**Layer:** L0 (Foundation)

## Purpose

Remove all Cohere-specific code from the `KeyPool` module to eliminate dead code and prepare the foundation for the Ollama migration. KeyPool is a shared module used by both the embedder (Cohere) and the LLM (Groq). Only the Cohere path is being removed; Groq key management must remain fully functional.

## Responsibilities

- Remove `FailureReason.COHERE_TRIAL_QUOTA` enum member
- Remove `_COHERE_TRIAL_RE` regex pattern
- Remove Cohere-specific branch in `classify_failure()`
- Remove `_DEFAULT_COOLDOWNS["cohere"]` entry
- Remove Cohere-specific test cases from `test_key_pool.py`
- Update provider-agnostic tests (rotation, from_env, logs) to not reference Cohere

## Public Interfaces

- `key_pool.py`: `KeyPool`, `KeyPool.from_env()`, `KeyPool.current()`, `KeyPool.mark_failed()`, `classify_failure()`, `FailureReason`, `AllKeysExhaustedError`
- `test_key_pool.py`: `TestClassifyFailure`, `TestKeyPoolRotation`, `TestFromEnv`, `TestNoRawKeysInLogs`, `TestEmbedderKeyPool`

**No interface changes** — only internal Cohere references removed. Groq consumers (llm.py) unaffected.

## Internal Dependencies

None (foundation layer).

## External Dependencies

- Python stdlib only (re, enum, threading, logging)

## Tasks (from execution plan)

| Task | Description | ACs |
|------|-------------|-----|
| KP-T1 | Remove Cohere enum, regex, and classify_failure branch from key_pool.py | AC-4 |
| KP-T2 | Remove Cohere cooldown, update KeyPool constructor | AC-4, Groq cooldown intact |
| KP-T3 | Remove Cohere-specific test cases from test_key_pool.py | AC-1 |
| KP-T4 | Update provider-agnostic tests (rotation, from_env, logs) | AC-1 |

## Acceptance Criteria

- AC-1: `pytest thermia-back/tests/retrieval/test_key_pool.py -v` — all remaining tests pass
- AC-4: `grep -ci "cohere" thermia-back/app/retrieval/key_pool.py` returns 0
- Groq enum values, classify_failure branches, and cooldowns are untouched
- No `FailureReason.COHERE_TRIAL_QUOTA` references remain anywhere

## Definition of Done

- [ ] key_pool.py has no Cohere references (grep verify)
- [ ] test_key_pool.py has no Cohere references
- [ ] All KeyPool tests pass (0 Cohere-related tests remain)
- [ ] Groq-specific test cases still pass
