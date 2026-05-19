# Code-Generation Plan: key-pool-fallback

**Run ID:** `2026-05-19t15-11-46z-api-key-fallback`
**Unit:** `key-pool-fallback`
**Layer:** 0 (single unit)
**Plan type:** Standard (requires human approval before code generation starts)
**Author:** code-generator agent, sub-stage 1

---

## Summary

Add a provider-agnostic `KeyPool` abstraction to `thermia-back/` that:
- Reads Cohere and Groq API keys from JSON arrays in `.env`
- Falls back to legacy single-key vars with a WARN log
- Rotates to the next healthy key after the in-key retry budget is exhausted
- Implements sticky-then-rotate strategy with per-provider cool-down windows
- Is thread-safe under FastAPI's async request handlers and ingest scripts
- Wires into `embedder.py`, `llm.py`, and `scripts/ingest.py`

All tasks follow TDD: Red test written first, then minimum code to green, then refactor.

---

## Files Locked (from input)

- `thermia-back/app/retrieval/key_pool.py` (new)
- `thermia-back/app/retrieval/embedder.py` (modify)
- `thermia-back/app/retrieval/llm.py` (modify)
- `thermia-back/scripts/ingest.py` (modify)
- `thermia-back/tests/retrieval/test_key_pool.py` (new)
- `thermia-back/.env.example` (modify)

---

## Task Checkboxes

### KP-T1 — `KeyPool` class skeleton + `FailureReason` enum

- [ ] **Red**: Write failing test asserting `KeyPool`, `FailureReason`, `AllKeysExhaustedError` are importable from `app.retrieval.key_pool`; assert `current()`, `mark_failed()`, `healthy_count()`, `from_env()` exist; assert `KeyPool(keys=["k1"])` constructor works.
- [ ] **Green**: Create `thermia-back/app/retrieval/key_pool.py` with `FailureReason` enum, `AllKeysExhaustedError` exception, and `KeyPool` class skeleton.
- [ ] **Refactor**: Add docstrings; verify no raw keys leak in `__repr__`.

**Files**: `thermia-back/app/retrieval/key_pool.py`, `thermia-back/tests/retrieval/test_key_pool.py`
**AC**: Class importable; all public methods defined; `from_env` is a classmethod; accepts explicit `keys` list.

---

### KP-T2 — `.env` parsing: JSON-array form + legacy fallback + boot fail-fast

- [ ] **Red**: Write failing tests for:
  - `from_env("cohere")` with `COHERE_API_KEYS='["k1","k2"]'` → 2-element pool
  - `from_env("cohere")` with single-quoted JSON and surrounding whitespace → parses correctly
  - `from_env("cohere")` with legacy `COHERE_API_KEY=k1` → 1-element pool + WARN log
  - `from_env("cohere")` with both `COHERE_API_KEYS` and legacy var → prefers `_KEYS` form
  - `from_env("cohere")` with no vars → raises `ValueError` naming the variable
  - `from_env("cohere")` with `COHERE_API_KEYS='[]'` → raises `ValueError`
  - `from_env("cohere")` with malformed JSON → raises `ValueError` naming variable
- [ ] **Green**: Implement `from_env` classmethod with JSON parsing, legacy fallback, and boot validation.
- [ ] **Refactor**: Extract helper `_parse_keys_env(provider, environ)` for testability.

**Files**: `thermia-back/app/retrieval/key_pool.py`, `thermia-back/tests/retrieval/test_key_pool.py`
**AC**: FR-2, FR-6 boot path fully covered.

---

### KP-T3 — Failure signal classifier (`classify_failure`)

- [ ] **Red**: Write failing tests for:
  - String containing `"429"` → `RATE_LIMIT_429`
  - String containing `"rate limit"` (case-insensitive) → `RATE_LIMIT_429`
  - Exception with `"429"` in message → `RATE_LIMIT_429`
  - String containing `"Trial key"` AND `"limited to"` AND `"API calls"` → `COHERE_TRIAL_QUOTA`
  - String containing `"daily"` AND `"token"` → `GROQ_DAILY_QUOTA`
  - String containing `"daily"` AND `"quota"` → `GROQ_DAILY_QUOTA`
  - String with `"500"` internal server error text → `PERSISTENT_5XX`
  - String `"503"` service unavailable → `PERSISTENT_5XX`
  - String `"400 bad request"` → `None`
  - String `"401 unauthorized"` → `None`
  - String `"403 forbidden"` → `None`
- [ ] **Green**: Implement `classify_failure(exc_or_text)` as a module-level function.
- [ ] **Refactor**: Compile regex patterns at module load; document the detection rules inline.

**Files**: `thermia-back/app/retrieval/key_pool.py`, `thermia-back/tests/retrieval/test_key_pool.py`
**AC**: FR-3 all signals covered; non-rotating 4xx returns `None`.

---

### KP-T4 — Cool-down dict + sticky-then-rotate cursor + thread-safe `mark_failed`

- [ ] **Red**: Write failing tests for:
  - `healthy_count()` on 2-key pool = 2
  - `current()` returns first key (index 0)
  - `mark_failed(RATE_LIMIT_429)` on 2-key pool → cursor advances to key 1
  - Consecutive calls to `current()` return the same key (sticky)
  - `mark_failed` on last key → wraps around to first non-failed key
  - `healthy_count()` == 0 after all keys marked failed → `current()` raises `AllKeysExhaustedError`
  - `mark_failed` emits `key_pool.rotated` INFO log with correct fields per FR-7 (no raw key material)
  - Degraded state (1 healthy key) emits `key_pool.degraded` WARN once per transition (not per call)
  - Exhausted state (0 healthy) emits `key_pool.exhausted` ERROR once per transition
  - Cool-down expiry: key failed at t0, `time.time()` mocked to `t0 + cooldown + 1` → re-enters pool
  - 50-concurrent-thread test: only 1 rotation event on first 429 for a 2-key pool
- [ ] **Green**: Implement `threading.Lock`, `_cooldowns` dict keyed by key-index, cursor advance with wrap-around, log emission, `AllKeysExhaustedError` on zero healthy, degraded/exhausted state transition tracking.
- [ ] **Refactor**: Extract `_next_healthy_index()` private method; ensure log fields match FR-7 spec exactly (hashed key id, no raw material).

**Files**: `thermia-back/app/retrieval/key_pool.py`, `thermia-back/tests/retrieval/test_key_pool.py`
**AC**: FR-4, FR-5, FR-6 runtime, FR-7, NFR-5 all covered.

---

### KP-T5 — Full unit-test suite for `KeyPool` (AC-1 + AC-3)

- [ ] **Verify**: Run all tests from KP-T1 through KP-T4 together under pytest; confirm all 11 AC-1 scenarios pass and all 3 AC-3 observability assertions pass.
- [ ] **Add**: Assert no raw key material in logs captured via `caplog` (regex scan over full log output).
- [ ] **Add**: `tests/retrieval/__init__.py` if missing.
- [ ] **Validate**: `pytest thermia-back/tests/retrieval/test_key_pool.py -v` → all green.

**Files**: `thermia-back/tests/retrieval/test_key_pool.py`, `thermia-back/tests/retrieval/__init__.py`
**AC**: Full AC-1 + AC-3 coverage; no raw keys in logs.

---

### KP-T6 — Wire `KeyPool` into `app/retrieval/embedder.py`

- [x] **Red**: Write failing test in `test_key_pool.py` (or a dedicated embedder-integration stub) verifying:
  - `get_query_embedding` calls the mock `cohere.Client` with the active key
  - On `RATE_LIMIT_429` after in-key budget exhausted, `KeyPool.mark_failed` is called and retry uses next key
  - On HTTP 400 (non-rotating), original exception is re-raised without calling `mark_failed`
  - Existing `test_retrieval.py` tests still pass
- [x] **Green**: Replace `_get_client()` singleton logic with `KeyPool`-driven client (module-level `_cohere_pool: KeyPool | None`); rebuild `_cohere_client` on rotation; integrate `classify_failure` into the retry loop.
- [x] **Refactor**: Keep `_RETRY_DELAYS` unchanged; ensure rotation only fires AFTER the in-key budget is exhausted.

**Files**: `thermia-back/app/retrieval/embedder.py`
**AC**: FR-8, FR-9 row 1; no regressions in `test_retrieval.py`.

---

### KP-T7 — Wire `KeyPool` into `app/retrieval/llm.py`

- [x] **Red**: Write failing test verifying:
  - `analyze_with_llm` reads active Groq key from `KeyPool.current()`
  - On `GROQ_DAILY_QUOTA` signal, pool rotates and call retries once on new key
  - On `AllKeysExhaustedError`, exception propagates for upstream Spanish error path
  - Existing `test_retrieval.py` tests still pass
- [x] **Green**: Add module-level `_groq_pool: KeyPool | None`; wrap `llm.invoke(messages)` in a try/except that classifies failure and rotates on rotating signals, retrying once; re-raise on non-rotating signals.
- [x] **Refactor**: Keep `ChatGroq` rebuilt per call (per FR-8/requirements §1.3).

**Files**: `thermia-back/app/retrieval/llm.py`
**AC**: FR-9 row 2; no regressions.

---

### KP-T8 — Wire `KeyPool` into `scripts/ingest.py` batch loop

- [x] **Red**: Write failing test (in `test_ingestion.py` or a stub) verifying:
  - `generate_embeddings` with a pool raises mid-batch, rotates, and continues
  - The same `KeyPool` singleton is used (not a new instance per file)
  - End-of-run total_inserted count is unaffected by mid-batch rotation
  - Existing `test_ingestion.py` tests still pass
- [x] **Green**: Replace `cohere_client = cohere.Client(cohere_api_key)` in `main()` with `KeyPool.from_env("cohere")`-based client; update `generate_embeddings` to accept pool + rebuild client on rotation.
- [x] **Refactor**: Ensure singleton reuse: `embedder.py` and `ingest.py` should use the same shared pool instance when run as a library (KP-T8 AC: same instance, not double-counted).

**Files**: `thermia-back/scripts/ingest.py`
**AC**: FR-9 row 3; FR-8 singleton rule; no regressions in `test_ingestion.py`.

---

### KP-T9 — Update `thermia-back/.env.example`

- [x] Replace `COHERE_API_KEY=your_cohere_api_key_here` and `GROQ_API_KEY=your_groq_api_key_here` with JSON-array forms.
- [x] Add comment block documenting:
  - (a) Legacy single-key fallback behaviour (FR-2)
  - (b) The ≥1-key rule with explicit error reference (FR-6)
  - (c) Optional `COHERE_KEY_COOLDOWN_SECONDS` / `GROQ_KEY_COOLDOWN_SECONDS` env vars with defaults
- [x] Verify: `grep -E '^COHERE_API_KEYS=' thermia-back/.env.example` returns exactly one line.

**Files**: `thermia-back/.env.example`
**AC**: AC-2 fully satisfied.

---

## Slice Order (Dependency Chain)

```
KP-T1 → KP-T2 → KP-T3 → KP-T4 → KP-T5 → KP-T6 → KP-T7 → KP-T8 → KP-T9
```

Each slice is green before the next starts. `KP-T5` is a verification+addition slice that consolidates the unit tests from T1-T4 and must pass completely before any call-site migration (T6-T8) begins.

---

## Pre-Mortem Notes (from execution plan §8)

1. Failure-signal classifier (KP-T3) is the most fragile: substring matching against provider error bodies. Mitigation: tests lock in the exact strings from requirements FR-3, so divergence from real SDK strings is caught later without redesign.
2. 50-concurrent-thread test (KP-T5): we use `threading.Barrier` to synchronise thread launch and a shared counter to assert exactly one cursor advance.
3. Ingest singleton (KP-T8): use a module-level `_COHERE_POOL` variable in `embedder.py`; `ingest.py` imports and reuses it rather than constructing a second pool.

---

*End of plan. Awaiting human approval before code generation begins.*
