# Requirements: API Key Fallback System for Cohere & Groq

**Run ID:** `2026-05-19t15-11-46z-api-key-fallback`
**Depth:** standard
**Project type:** brownfield (Python/FastAPI backend `thermia-back/`)
**Author:** Requirements Analyst (AIDLC factory, Pass 2)
**Source request:**
> "We are using API keys from free-tier Cohere and Groq accounts. I need
> you to create a fallback system so that if one account starts failing
> due to usage limits, the application automatically switches to a
> different API key. Use a dynamic list of API keys stored in the .env
> file. It should support adding as many API keys as needed, with no
> hard limit, but there must always be at least one key available."

---

## 1. Intent Analysis

### 1.1 Classification

| Axis | Value | Notes |
|---|---|---|
| Clarity | Clear | Concrete request: fallback on failure, dynamic list in `.env`, ≥1 key required. |
| Type | New Feature | Adds a capability that does not exist today. |
| Scope | Multiple Components | Touches `embedder.py`, `llm.py`, `scripts/ingest.py`, `.env.example`, plus a new module. |
| Complexity | Moderate | Rotation policy, persistence policy, env parsing, multi-signal failure detection. |
| Depth | standard | Per `aidlc-rules/aws-aidlc-rule-details/common/depth-levels.md` for Clear + Multiple Components + Moderate. |

### 1.2 Primary Outcomes (from Q1, answer D)

In priority order:

1. **Availability (primary).** End users on `POST /analyze` must never see
   `"El servicio de análisis no está disponible temporalmente."` because a
   *single* free-tier key was exhausted, as long as ≥1 key in the pool
   still has capacity.
2. **Cost / quota optimisation.** Combined free-tier budget is stretched
   across multiple keys before any paid usage is needed.
3. **Operational resilience.** When one account is throttled or revoked,
   the system silently moves on without a redeploy or restart.

### 1.3 Existing Behaviour (baseline)

Three call sites currently hold a single API key:

| File | Variable | Lifecycle |
|---|---|---|
| `thermia-back/app/retrieval/embedder.py` (L25–28) | `COHERE_API_KEY` | Module-level singleton `cohere.Client`. Already retries 3× on 429 with 10/30/60 s back-off. |
| `thermia-back/app/retrieval/llm.py` (L51) | `GROQ_API_KEY` | `ChatGroq` rebuilt per call; no singleton; no retry today. |
| `thermia-back/scripts/ingest.py` (L405–410) | `COHERE_API_KEY` | Fresh `cohere.Client` per ingest run; in-batch back-off already present elsewhere. |

The new fallback layer composes *above* the existing in-key 3-retry budget
on Cohere: rotation occurs **only after** the in-key budget is exhausted,
not on the first 429.

---

## 2. Functional Requirements

### FR-1 — Key Pool Module
A new module `thermia-back/app/retrieval/key_pool.py` MUST implement a
provider-agnostic `KeyPool` abstraction with at minimum:

- `KeyPool.from_env(provider: str) -> KeyPool` — class-method constructor
  that reads `<PROVIDER>_API_KEYS` from `os.environ` (see FR-2).
- `KeyPool.current() -> str` — returns the currently active key.
- `KeyPool.mark_failed(reason: FailureReason) -> None` — records the
  current key as dead, advances to the next healthy key, emits a
  structured log line per FR-7.
- `KeyPool.healthy_count() -> int` — count of keys not currently in
  cool-down.

The module MUST be thread-safe under FastAPI's async request handling
(an `asyncio.Lock` or a `threading.Lock` is acceptable; the choice is
deferred to construction).

### FR-2 — `.env` Storage Format (from Q2, answer C)
API keys MUST be stored as a **JSON array per provider** in `.env`:

```
COHERE_API_KEYS='["k1","k2","k3"]'
GROQ_API_KEYS='["ka","kb"]'
```

- Order in the JSON array = priority order (used by FR-5 sticky-then-rotate).
- Parsing MUST be tolerant of surrounding whitespace and single- or
  double-quoted JSON; on parse failure the system MUST fail fast at boot
  with a clear error message naming the malformed variable.
- **Backwards compatibility:** if `<PROVIDER>_API_KEYS` is absent but the
  legacy single-key var (`COHERE_API_KEY` / `GROQ_API_KEY`) is present,
  the system MUST treat the legacy value as a one-element pool and log a
  one-time WARN suggesting migration to the array form.

### FR-3 — Rotation-Triggering Failure Signals (from Q3, answer C)
The system MUST rotate to the next key on **any** of the following,
each evaluated **after** the in-key retry budget (Cohere: 3 × back-off
10/30/60 s) is exhausted:

| Signal | Detection rule |
|---|---|
| HTTP 429 (rate-limited) | Exception/response containing `"429"` or `"rate limit"` (case-insensitive). Current Cohere code already classifies this. |
| Cohere Trial-key quota | Response body contains `"Trial key"` or `"limited to"` AND `"API calls"`. (Per Q3 example: `{"status_code": 429, "body": {"message": "You are using a Trial key, which is limited to 1000 API calls / month..."}}`.) |
| Groq daily-token quota | Response/exception text mentions `"daily"` AND (`"token"` OR `"quota"`) — provider-specific quota-exceeded signal. |
| 5xx after in-key retry budget | Any HTTP 5xx that persists across the 3 in-key retries. |

For signals not in this list (e.g. 4xx other than 429), the call MUST
NOT rotate — it MUST surface the original exception. This avoids
treating a malformed-input bug as a key health problem.

### FR-4 — Dead-Key Persistence Policy (from Q4, answer A + per-provider override)
After a key triggers rotation, it MUST enter a cool-down window:

| Provider | Cool-down window | Env var | Default |
|---|---|---|---|
| Cohere | 30 days (typical monthly Trial-key reset) | `COHERE_KEY_COOLDOWN_SECONDS` | `2592000` |
| Groq | 1 day (typical daily token reset) | `GROQ_KEY_COOLDOWN_SECONDS` | `86400` |

- Cool-down state is **in-process only** (Python dict keyed by hashed
  key id). It is NOT persisted to disk or to PostgreSQL; a process
  restart resets all cool-downs.
- When the cool-down expires, the key re-enters the healthy pool at
  its original priority position.

### FR-5 — Rotation Strategy (from Q6, answer D — sticky-then-rotate)
- The pool MUST start each process with the first key in `.env` order
  as the active key.
- The active key MUST be reused for every subsequent call until it
  fails per FR-3.
- On failure, the pool MUST advance to the **next healthy key in
  declaration order** (NOT round-robin, NOT random) and stick to that
  one until *it* fails.
- If the end of the list is reached, the pool MUST wrap around to the
  first key whose cool-down has expired.

### FR-6 — Minimum-Key Enforcement (from Q5, answer B)

**Boot-time:**
- If zero keys are configured for a provider that the running code path
  needs (Cohere for `embedder` + `ingest`; Groq for `llm`), the system
  MUST raise `ValueError` and refuse to start. The error message MUST
  name the missing variable and reference the `.env.example` block.

**Runtime:**
- When the pool transitions to a state where only **one** healthy key
  remains, the system MUST emit a **WARN** structured log
  (`level=WARN`, `event="key_pool.degraded"`, `provider`,
  `keys_remaining=1`).
- When the pool transitions to **zero** healthy keys, the system MUST
  emit an **ERROR** structured log
  (`level=ERROR`, `event="key_pool.exhausted"`, `provider`) and raise
  an upstream exception so the existing `POST /analyze` error path can
  surface the existing Spanish error message (`"El servicio de análisis
  no está disponible temporalmente."`).
- The system MUST NOT expose a new `/healthz` endpoint or extend an
  existing one for per-provider key counts (option C was rejected).

### FR-7 — Observability (from Q9 D)
Every key rotation event MUST emit exactly one structured log line at
`level=INFO` with the fields:

```
event=key_pool.rotated
provider=<cohere|groq>
key_index_from=<int>
key_index_to=<int>
reason=<429|cohere_trial|groq_daily|5xx>
keys_remaining=<int>
```

- The log line MUST NOT contain raw key material (no full keys, no
  suffixes longer than 4 characters, no Base64-decoded fragments).
- A short hash (`hashlib.sha256(key)[:8]`) MAY be included as
  `key_id_hash` for cross-referencing.

### FR-8 — Cohere Client Lifecycle (from Q7, answer B)
- `embedder.py` MUST keep a single module-level `cohere.Client`
  reference, but the reference MUST be **rebuilt** with the new key
  whenever the pool rotates. This preserves "one HTTP connection pool
  at a time" semantics while accepting the cost of a client rebuild
  on rotation (rare event by design).
- `scripts/ingest.py` MUST use the same `KeyPool` instance and follow
  the same rebuild-on-rotation rule.
- Groq is unaffected: `ChatGroq` is already rebuilt per call, so it
  reads the active key from the pool each invocation.

### FR-9 — Scope of Adoption (from Q8, answer B)
The fallback system MUST be wired into:

| Call site | Provider | Required |
|---|---|---|
| `app/retrieval/embedder.py::get_query_embedding` | Cohere | yes |
| `app/retrieval/llm.py::analyze_with_llm` | Groq | yes |
| `scripts/ingest.py::main` (the batch embed loop) | Cohere | yes |

A long-running ingest MUST survive one Cohere account exhausting
mid-batch by rotating to the next key and continuing without
restart.

Other future providers (e.g. OpenAI) are **out of scope** for this
run, but the `KeyPool` abstraction MUST be provider-agnostic so a
later run can add them without redesign.

### FR-10 — `.env.example` Documentation (from Q9 C)
`thermia-back/.env.example` MUST be updated to:

- Replace `COHERE_API_KEY=…` and `GROQ_API_KEY=…` with the new
  `COHERE_API_KEYS='["…"]'` / `GROQ_API_KEYS='["…"]'` form.
- Document the legacy fallback behaviour (FR-2) in a comment block.
- State the ≥1-key rule (FR-6) explicitly.
- Document the optional `COHERE_KEY_COOLDOWN_SECONDS` /
  `GROQ_KEY_COOLDOWN_SECONDS` env vars with their defaults.

---

## 3. Non-Functional Requirements

### NFR-1 — Reliability / Availability
- **Availability target:** the `POST /analyze` endpoint MUST NOT return
  the Spanish "service unavailable" error due to *single-key* quota
  exhaustion as long as ≥1 key in the pool has capacity. Failure of
  *all* keys remains a legitimate degraded state.
- **Rotation latency budget:** a rotation event (detection → switch →
  retry on next key) MUST add no more than the existing in-key retry
  budget already adds today (≤100 s wall-clock for Cohere; Groq has no
  in-key retries today). No additional sleep is mandated for rotation
  itself.

### NFR-2 — Security
- Raw API keys MUST NOT appear in any log line, exception message,
  HTTP response body, or persisted artefact.
- The `.env` file remains the only source of truth for keys; the
  pool MUST NOT write keys back to disk.
- Hashed key identifiers (`sha256(key)[:8]`) MAY appear in logs; full
  keys never.

### NFR-3 — Maintainability
- The `KeyPool` module MUST be unit-testable in isolation: failure
  signals MUST be expressible as inputs to a method (e.g. `mark_failed`
  takes a reason enum), not as raw `cohere.Client` exceptions buried
  in HTTP-layer code.
- The module MUST expose a constructor that accepts an explicit key
  list, for tests that do not want to monkey-patch `os.environ`.

### NFR-4 — Backwards Compatibility
- Existing deployments using `COHERE_API_KEY` and `GROQ_API_KEY` (single
  scalar) MUST continue to work with no `.env` change, per FR-2.
- The current `POST /analyze` request/response schema MUST NOT change.
- The current `POST /analyze` user-facing Spanish error message MUST be
  preserved verbatim for the "all keys exhausted" case.

### NFR-5 — Concurrency
- The pool MUST be safe to call from concurrent FastAPI request
  handlers without two requests double-incrementing the cursor or
  missing a rotation event.
- The `ingest.py` script is single-threaded and inherits the same
  guarantees trivially.

### NFR-6 — Observability
- All rotation events, degraded states (≤1 healthy), and exhausted
  states (0 healthy) MUST produce structured logs per FR-6 and FR-7.
- No new metrics endpoint is required (Q5 rejected option C).

---

## 4. User Scenarios

### S-1 — Happy path with healthy pool
A user submits a PDF to `POST /analyze`. `embedder.py` calls Cohere
using the active key. The key is healthy. The response is 200, no
rotation event is emitted.

### S-2 — Cohere Trial-key quota exhausts mid-request
`embedder.py` calls Cohere. The in-key 3-retry budget is exhausted on
the Trial-key quota error. The pool marks the key dead (30-day cool-down)
and rotates to the next key. The retry on the new key succeeds. The
user sees a normal 200 response, slightly delayed by the in-key retry
budget. One `key_pool.rotated` INFO log is emitted.

### S-3 — Groq daily quota exhausts
`llm.py` calls Groq. The daily-token quota signal is detected. The pool
rotates to the next Groq key (24-hour cool-down on the failed one).
The retry succeeds. One `key_pool.rotated` INFO log is emitted.

### S-4 — All Cohere keys exhausted
All configured Cohere keys are in cool-down. `embedder.py` raises.
`POST /analyze` returns 500 with the existing Spanish error message.
One `key_pool.exhausted` ERROR log is emitted.

### S-5 — Boot with zero keys
The operator deploys with `COHERE_API_KEYS='[]'` (or omits both
`COHERE_API_KEYS` and the legacy `COHERE_API_KEY`). The FastAPI
process refuses to start, raising `ValueError` referencing
`.env.example`.

### S-6 — Long-running ingest survives mid-batch exhaustion
The operator runs `python -m scripts.ingest`. After ~10 minutes one
Cohere key exhausts. The pool rotates; the ingest continues without
restart. The summary at the end reports the total documents inserted
unchanged; the rotation appears in logs.

---

## 5. Acceptance Criteria

Selected by user: **A + C + D** (unit tests, documentation, observability).
Integration test (B) is **explicitly NOT required** for this run.

### AC-1 — Unit tests (mandatory)
A `pytest` test module (suggested path:
`thermia-back/tests/retrieval/test_key_pool.py`) MUST cover, with the
provider client mocked:

- ✅ Boot fail-fast: zero-key pool raises `ValueError` with a message
  naming the missing env var.
- ✅ Rotation on 429: simulated 429 after in-key retry budget switches
  to the next key.
- ✅ Rotation on Cohere Trial-key signal: simulated Trial-key body
  switches keys.
- ✅ Rotation on Groq daily-token signal: simulated daily-token error
  switches keys.
- ✅ Rotation on persistent 5xx: simulated 5xx after retry budget
  switches keys.
- ✅ Non-rotating 4xx: simulated 400 / 401 / 403 surfaces the original
  exception without rotating.
- ✅ All keys exhausted: raises the documented exception so the
  upstream handler can produce the Spanish error message.
- ✅ Cool-down expiry: a key marked failed at `t0` re-enters the pool
  at `t0 + cooldown_seconds` (mock `time.time`).
- ✅ Sticky-then-rotate: the same healthy key is reused across
  consecutive calls until it fails.
- ✅ Concurrency: 50 concurrent calls against a pool with one bad key
  produce exactly one rotation event (not 50).
- ✅ Legacy var compatibility: `COHERE_API_KEY=…` (no `_KEYS`) is
  treated as a one-element pool with a WARN log.

### AC-2 — `.env.example` documentation (mandatory)
- ✅ `thermia-back/.env.example` shows the new `COHERE_API_KEYS` /
  `GROQ_API_KEYS` JSON-array form with a worked example.
- ✅ A comment block explains the legacy fallback (FR-2), the ≥1-key
  rule (FR-6), and the cool-down env vars (FR-4).

### AC-3 — Observability (mandatory)
- ✅ Each rotation event produces exactly one INFO log line with the
  fields listed in FR-7.
- ✅ Degraded-state (1 healthy) emits exactly one WARN log per
  transition, not per call.
- ✅ Exhausted-state (0 healthy) emits exactly one ERROR log per
  transition.
- ✅ No raw key material appears in any log captured during the unit
  test suite (assert by regex search over `caplog`).

### AC-4 — Integration test (NOT required for sign-off)
Out of scope per Q9. May be added later as a follow-up task.

---

## 6. Out of Scope

The following are explicitly **not** part of this run:

- A FastAPI `/healthz` or `/metrics` endpoint exposing per-provider key
  counts (Q5 option C rejected).
- Persisting cool-down state to disk or PostgreSQL across process
  restarts (FR-4 is in-process only by design).
- Adding new providers (OpenAI, Anthropic, etc.). The abstraction must
  support them; wiring them is a future run.
- Frontend (`thermia-front/`) changes. The user-facing Spanish error
  message remains unchanged, so no frontend work is needed.
- Migration tooling to convert existing single-key deployments — the
  legacy fallback in FR-2 handles this without operator action.
- Integration / end-to-end tests against real Cohere / Groq endpoints.

---

## 7. Open Questions / Deferred Decisions

None blocking. The following minor decisions are **delegated to the
construction stage** because they do not change the spec:

- Whether the lock is `asyncio.Lock` or `threading.Lock` — choose based
  on how the call sites invoke the pool (FastAPI handlers use both).
- Exact module layout: a single `key_pool.py` vs. a small package
  (`key_pool/__init__.py` + `key_pool/_signals.py`). Constructor's
  call.
- Whether to emit one structured-log JSON line per event or use the
  existing Python `logging` formatter — match whatever the rest of
  `thermia-back` already does.

---

## 8. Traceability Matrix (Questions → Requirements)

| Question | Axis | User Answer | Driven Requirements |
|---|---|---|---|
| Q1 | Purpose | D | §1.2 (availability primary; cost + resilience secondary) |
| Q2 | Needs | C | FR-2 (JSON array per provider; legacy fallback) |
| Q3 | Needs | C + Cohere Trial-key example | FR-3 (multi-signal failure detection) |
| Q4 | Limits | A + per-provider (Cohere 30 d, Groq 1 d) | FR-4 (cool-down windows + env vars) |
| Q5 | Limits | B | FR-6 (boot fail-fast, WARN at 1, ERROR at 0; no `/healthz`) |
| Q6 | Expectations | D | FR-5 (sticky-then-rotate) |
| Q7 | Expectations | B | FR-8 (single Cohere client, swap key on rotation) |
| Q8 | Context | B | FR-9 (runtime + ingestion in scope; future providers out) |
| Q9 | Acceptance | A + C + D | AC-1, AC-2, AC-3 (integration test AC-4 explicitly out) |

---

*End of requirements document. Next stage: planning (decompose FRs/NFRs
into ordered implementation tasks).*
