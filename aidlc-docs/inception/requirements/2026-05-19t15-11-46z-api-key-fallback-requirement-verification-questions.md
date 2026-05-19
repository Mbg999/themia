# Requirement Verification Questions
**Run ID:** 2026-05-19t15-11-46z-api-key-fallback
**Feature:** API Key Fallback System for Cohere & Groq
**Pass:** 1 (clarifying questions — await answers before generating requirements.md)

---

## Context

The current backend uses a **single** API key per provider:

- `thermia-back/app/retrieval/embedder.py` reads `COHERE_API_KEY` (singleton client).
- `thermia-back/app/retrieval/llm.py` reads `GROQ_API_KEY` at every call.
- `thermia-back/scripts/ingest.py` reads `COHERE_API_KEY` for batch embedding.

The existing Cohere code already retries up to 3 times with exponential back-off
(10/30/60s) on HTTP 429 from the **same** key. This feature adds **key-level
fallback**: when a key exhausts its free-tier quota, the system must switch to
the next available key automatically. The list of keys must live in `.env`, be
of unbounded length, and require at least one key.

The questions below resolve ambiguities so that requirements.md is precise about
*detection*, *rotation policy*, *persistence*, *acceptance criteria*, and
*scope*. Please answer all 9 questions; combine letters (e.g., "A + C") when
multiple options apply.

---

<!-- axis: Purpose -->
## Question 1: Primary Purpose of the Fallback System

The stated goal is to keep the application running when one free-tier key
fails. Which of the following best describes the **primary** outcome you want
to guarantee?

A) **Availability** — end users never see a "service unavailable" error caused
   by quota exhaustion of a single key, as long as ≥1 key in the pool still has
   capacity.
B) **Cost / quota optimisation** — distribute load across keys to extend the
   combined free-tier budget before any paid usage is needed.
C) **Operational resilience** — when one account is throttled or revoked, the
   system silently moves on without a redeploy or restart.
D) All of the above, with A being the most important.
X) Other (please describe after [Answer]: tag below)

[Answer]: D

---

<!-- axis: Needs -->
## Question 2: `.env` Storage Format

How should the dynamic list of API keys be encoded in `.env`? (The current
single-key vars are `COHERE_API_KEY` and `GROQ_API_KEY`.)

A) **Comma-separated list per provider** — `COHERE_API_KEYS=k1,k2,k3` and
   `GROQ_API_KEYS=ka,kb`. Order in the string = priority order. Backwards-compat:
   if `COHERE_API_KEYS` is absent, fall back to the legacy `COHERE_API_KEY`.
B) **Numbered keys, auto-discovered** — `COHERE_API_KEY_1`, `COHERE_API_KEY_2`,
   …, scanned on startup. Easy to add/remove a single line in `.env`.
C) **JSON array per provider** — `COHERE_API_KEYS='["k1","k2","k3"]'`. Most
   structured but harder to edit.
D) **Keep `COHERE_API_KEY` as primary; add `COHERE_API_KEY_FALLBACK_1..N` as
   fallback** — preserves existing var name; new fallbacks are explicit.
X) Other (please describe after [Answer]: tag below)

[Answer]: C

---

<!-- axis: Needs -->
## Question 3: Failure Signals That Trigger Rotation

Which API responses should be treated as "this key is failing — switch to the
next one"? (The existing code already retries 429 three times on the **same**
key with back-off; rotation would happen on **persistent** failure.)

A) **HTTP 429 (rate-limited)** only — after the existing 3-retry budget on a
   single key is exhausted, move to the next key.
B) **HTTP 429 + HTTP 401/403 (auth failure / revoked key)** — both quota and
   credential failures rotate.
C) **Any quota-related signal** — 429, plus provider-specific quota-exceeded
   responses (e.g. Cohere "trial key" / monthly-cap errors, Groq daily-token
   limits), plus 5xx after the in-key retry budget.
D) **All non-2xx after the in-key retry budget** — most aggressive; treats any
   sustained failure on a key as a reason to try the next one.
X) Other (please describe after [Answer]: tag below)

[Answer]: C, example of cohere trial key error:
```json
{
   "status_code": 429,
   "body": {
      "id": "3e979f4a-9ff2-425f-acfb-076d09c5ab32",
      "message": "You are using a Trial key, which is limited to 1000 API calls / month. You can continue to use the Trial key for free or upgrade to a Production key with higher rate limits at 'https://dashboard.cohere.com/api-keys'. Contact us on 'https://discord.gg/XW44jPfYJu' or email us at support@cohere.com with any questions"
      }
}
```

---

<!-- axis: Limits -->
## Question 4: Dead-Key Persistence Policy

After a key fails and is rotated away, when (if ever) does the system try it
again?

A) **Cool-down window** — mark the key dead for a configurable window
   (e.g. 60 minutes), then re-admit it to the pool. Default window:
   `KEY_COOLDOWN_SECONDS=3600`.
B) **Dead for the process lifetime** — once a key fails, never retry it until
   the FastAPI process / ingest script restarts. Simple, but a transient outage
   permanently disables a key until redeploy.
C) **Never persist failure across calls** — every call starts at the head of
   the list. Simplest, but means a known-bad key keeps being tried first.
D) **Per-failure-mode policy** — 429 uses a cool-down (transient quota);
   401/403 is dead for process lifetime (credential is revoked).
X) Other (please describe after [Answer]: tag below)

[Answer]: A) cohere dead for 1 month, groq dead for 1 day (based on typical quota reset patterns observed in practice).

---

<!-- axis: Limits -->
## Question 5: Minimum-Key Enforcement and Exhaustion Behavior

The request states "there must always be at least one key available". How
should the system enforce this at boot and at runtime?

A) **Boot**: if zero keys are configured for a provider, fail fast on startup
   (raise `ValueError` like the current embedder does).
   **Runtime**: when all keys are exhausted, raise an upstream error and let
   the existing `POST /analyze` Spanish error message (`"El servicio de
   análisis no está disponible temporalmente."`) surface to the user.
B) **Boot** as in A.
   **Runtime**: when only one key remains healthy, emit a WARN log; when zero
   remain, ERROR-log and raise.
C) Same as B, plus expose `/healthz` (or extend an existing endpoint) with a
   per-provider count of healthy keys for ops visibility.
D) **Boot** as in A.
   **Runtime**: if all keys are dead, attempt the cool-down list anyway (best
   effort) before raising — gives the system one more chance under transient
   provider outages.
X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

<!-- axis: Expectations -->
## Question 6: Rotation Strategy (How the Next Key Is Chosen)

When a call needs a key, which key in the pool is used?

A) **Priority + round-robin on failure** — always start with the first healthy
   key in `.env` order; only advance the cursor when the current key fails.
   Predictable, easy to debug.
B) **Round-robin always** — each call picks the next healthy key in rotation,
   distributing load evenly and extending combined quota.
C) **Random healthy key** — pick uniformly at random from the healthy set.
   Spreads load with no shared state across workers.
D) **Sticky-then-rotate** — keep using the current key until it fails, then
   pick the next healthy one and stick to it (same effect as A in practice).
X) Other (please describe after [Answer]: tag below)

[Answer]: D

---

<!-- axis: Expectations -->
## Question 7: Scope of Cohere Singleton Client

`app/retrieval/embedder.py` currently caches a single `cohere.Client` as a
module-level singleton. To support multiple keys, the singleton model must
change. Which design do you prefer?

A) **One client per key**, cached by key string in a dict. Keep all live
   `cohere.Client` instances around; the rotation manager picks which one to
   call. Reuses connection pools per key.
B) **Single client, swap its API key** on rotation — rebuilds the client object
   (cheap; one HTTP pool at a time). Simpler invariants.
C) **No client caching** — construct a fresh `cohere.Client(key)` for every
   call. Cleanest but loses pool reuse (slightly slower under load).
D) Same approach as Cohere should also apply to Groq's `ChatGroq` instance
   (which is currently rebuilt on every call — no singleton needed).
X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

<!-- axis: Context -->
## Question 8: Scope — Which Code Paths Get the Fallback?

The codebase has three places that hold API keys. Which of these must use the
new fallback system?

A) **Runtime only** — `POST /analyze` request path
   (`app/retrieval/embedder.py` + `app/retrieval/llm.py`). The ingestion
   script keeps using a single key (it runs offline, can be restarted).
B) **Runtime + ingestion** — also wire `scripts/ingest.py` (batch Cohere
   embeddings) to the same key pool, so a long-running ingest can survive
   one account exhausting mid-batch.
C) **Runtime + ingestion + future providers** — design a small provider-agnostic
   `KeyPool` abstraction so adding (say) OpenAI later is mechanical.
D) Runtime only for now; document the abstraction so ingestion adoption is a
   later, smaller task.
X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

<!-- axis: Acceptance -->
## Question 9: Acceptance Criteria & Tests

How will we know this works? Which of these are required to mark the feature
"done"? (Choose all that apply.)

A) **Unit tests** — mock provider client, verify that on simulated quota
   failure the next key is used and that all-keys-exhausted raises the
   expected error. (Mandatory.)
B) **Integration test** — start the FastAPI app with a `.env` containing 2
   dummy keys (first one configured to fail via mock), POST `/analyze`, assert
   200 and that the second key was used.
C) **Documentation** — update `.env.example` with the new `*_KEYS` (or
   numbered) variables, with a comment block explaining the format and the
   ≥1-key rule. Update `aidlc-docs/inception/reverse-engineering/` if it
   gets generated for this run.
D) **Observability** — every rotation event emits a structured log line
   (`key_index`, `provider`, `reason`, `keys_remaining`). No raw key material
   ever appears in logs.
X) Other (please describe after [Answer]: tag below)

[Answer]: A + C + D

---

*Answer by filling in the letter (A/B/C/D/X) after each `[Answer]:` tag. For X,
add your description on the same or next line. You can combine letters
(e.g., "A + D") when multiple options apply.*
