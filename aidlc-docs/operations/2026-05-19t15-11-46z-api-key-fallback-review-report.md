# Code Review Report

Run: `2026-05-19t15-11-46z-api-key-fallback`
Reviewers: code-quality, security, simplifier

## Summary

| Severity | code-quality | security | simplifier | Total |
|---|---|---|---|---|
| P0 | 0 | 0 | 0 | 0 |
| P1 | 4 | 5 | 0 | 9 |
| P2 | 4 | 4 | 2 | 10 |
| P3 | 2 | 2 | 2 | 6 |

_Total findings across all reviewers:_ **25**

## Code Quality

Status: `complete`

### [P1] thermia-back/app/retrieval/embedder.py:61

_get_client() has no key-tracking guard — it rebuilds only when _cohere_client is None, relying on callers to null out the singleton after rotation; this fragile implicit contract will break if a second consumer uses the pool+client

**Recommendation:** Store the key that was used to build the current client (e.g., _cohere_client_key: str | None = None). In _get_client(), compare pool.current() to _cohere_client_key and rebuild if they differ. Remove the requirement for callers to set _cohere_client = None manually.

**Axis:** design

### [P1] thermia-back/app/retrieval/key_pool.py:77

_5XX_RE regex can false-positive on large numbers containing '5xx' substrings (e.g., '15000') — the comment claims a digit-prefix guard exists but the code only range-checks the extracted 3-char value

**Recommendation:** Use a word-boundary or negative look-behind in the regex: re.compile(r'(?<!\d)5\d{2}(?!\d)') so that '500' in '15000' or '5002' does not match. Remove the misleading comment about digit-prefix detection.

**Axis:** correctness

### [P1] thermia-back/app/retrieval/key_pool.py:265

_was_degraded and _was_exhausted flags are never reset when cool-down expires and keys recover, suppressing future log transitions

**Recommendation:** Reset _was_degraded and _was_exhausted to False when healthy_count rises back above the threshold that originally triggered each flag. Check on every mark_failed call after computing the new healthy count, and also in _current_unlocked when a cool-down expiry re-adds a key.

**Axis:** correctness

### [P1] thermia-back/scripts/ingest.py:416

Ingest cohere_client is a fixed snapshot — key rotation is inoperative during ingestion

**Recommendation:** Replace the standalone cohere.Client construction with a call to embedder.get_query_embedding per batch, or pass the KeyPool into generate_embeddings and re-acquire pool.current() on each batch call so that a rotated key is actually used.

**Axis:** correctness

### [P2] thermia-back/app/retrieval/key_pool.py:207

Transition-tracking flags _was_degraded and _was_exhausted conflate rotation logic with log-deduplication in a single method, reducing cohesion

**Recommendation:** Extract the log-deduplication concern into a small _emit_state_transition(healthy_count) helper that owns the flag transitions. mark_failed calls it after updating the cursor. This makes each concern independently testable.

**Axis:** maintainability

### [P2] thermia-back/tests/retrieval/test_key_pool.py:133

classify_failure edge case — a string containing a large integer with an embedded 5xx substring (e.g. '15000 items processed') is not tested and would currently return PERSISTENT_5XX incorrectly

**Recommendation:** Add a parametrized test: test_5xx_false_positive_in_large_number that passes strings like 'processed 15000 tokens' and asserts the result is None.

**Axis:** testing

### [P2] thermia-back/tests/retrieval/test_key_pool.py:282

No test for flag-reset behaviour: _was_degraded / _was_exhausted are not re-armed when cool-down expires, so the once-per-transition semantics cannot be confirmed for the recovery path

**Recommendation:** Add a test that: (1) exhausts all keys so _was_exhausted fires, (2) manually resets _cooldowns to force expiry, (3) calls mark_failed again on a newly-failed key, and asserts the ERROR log fires a second time (proving the flag was re-armed).

**Axis:** testing

### [P2] thermia-back/tests/retrieval/test_key_pool.py:290

test_50_concurrent_threads_single_rotation asserts only the final state, not the rotation count — the comment says 'exactly 1 rotation' but rotation_count is never asserted

**Recommendation:** Assert that pool._cooldowns has exactly one entry (key 0 in cool-down) after the concurrent run, confirming that mark_failed for an already-cooled-down key does not advance the cursor a second time. Or assert rotation_count == 1 if you track it via a mock.

**Axis:** testing

### [P3] thermia-back/app/retrieval/key_pool.py:145

_DEFAULT_COOLDOWNS is a bare module-level dict — adding a new provider requires editing both _DEFAULT_COOLDOWNS and _get_cooldown_seconds, which are separated by several lines and easy to miss

**Recommendation:** Consolidate provider defaults into a single _PROVIDER_CONFIG dict or dataclass: {provider: {cooldown_seconds: N, ...}} so _get_cooldown_seconds only reads from one place.

**Axis:** maintainability

### [P3] thermia-back/scripts/ingest.py:298

enumerate([0, *_EMBED_RETRY_DELAYS]) is non-obvious — the zero-delay sentinel first element and the unpacking pattern are subtle for readers unfamiliar with the retry idiom

**Recommendation:** Replace with an explicit loop: attempt = 0; for delay in [0] + list(_EMBED_RETRY_DELAYS): ... and add a brief comment: '# first pass has no delay; subsequent passes back off'.

**Axis:** readability

## Security

Status: `complete`

### [P1] thermia-back/app/main.py:61

Authentication is entirely bypassed when THERMIA_ENV=local. If THERMIA_ENV is unset or accidentally set to 'local' in a non-local environment (e.g., a staging container whose .env was copied from a developer machine), every POST /analyze call executes without any bearer-token check. There is no defence against this misconfiguration.

**Recommendation:** Remove the environment-gated bypass. For local development, set API_KEY to a well-known dev token in .env.example and document it. Alternatively, check against a non-empty API_KEY value and fail startup if the key is absent, regardless of THERMIA_ENV.

**Refs:** CWE-284, A01:2021

### [P1] thermia-back/app/main.py:63

API_KEY is read at request time from os.environ on every call. If API_KEY is absent (empty string), the comparison 'authorization[len("Bearer "):] != api_key' succeeds for any request that sends 'Bearer ' (empty bearer), silently granting access. The empty default ('') makes this a no-auth-by-default condition when API_KEY is not configured.

**Recommendation:** At application startup, assert that API_KEY is non-empty (len >= 16). Raise a startup error if it is missing or empty. Use constant-time comparison: 'import hmac; hmac.compare_digest(token, api_key)' to prevent timing-oracle attacks.

**Refs:** CWE-312, A02:2021

### [P1] thermia-back/app/retrieval/embedder.py:61

Race condition in _get_client(): pool key can rotate between pool.current() and cohere.Client(active_key) construction, causing the rebuilt client to use a stale (possibly exhausted) key.

**Recommendation:** Atomically snapshot the active key under KeyPool's internal lock and pass it directly to the client constructor; alternatively compare pool.current() after building the client and rebuild if it changed.

**Refs:** CWE-362, A04:2021

### [P1] thermia-back/app/retrieval/embedder.py:123

assert statement used to enforce runtime invariant (assert last_exc is not None). In Python optimised mode (-O / PYTHONOPTIMIZE) assert statements are compiled out, converting this into an UnboundLocalError crash that bypasses the intended control flow.

**Recommendation:** Replace with an explicit runtime guard: 'if last_exc is None: raise RuntimeError("unexpected: no exception after retry budget")'. Never use assert for enforcing production invariants.

**Refs:** CWE-617, A05:2021

### [P1] thermia-back/app/retrieval/key_pool.py:104

_parse_keys_env() strips a single-layer of surrounding single-quotes from the raw env value before JSON parsing. Malformed values such as "'[\"k1\"]' extra" are silently truncated to '["k1"]' extra and then fail JSON decoding with a cryptic error instead of a clear validation message. More critically, an attacker who can control the env var value (e.g., via .env file injection in a CI pipeline) can embed arbitrary JSON, since no key-format validation (prefix check, minimum length, character allowlist) is performed on the parsed key strings.

**Recommendation:** After JSON parsing, validate each key string against a minimal format rule (non-empty, minimum length >= 8, printable ASCII / alphanumeric + hyphens only). Log the number of keys loaded but never any key material.

**Refs:** CWE-20, A03:2021

### [P2] thermia-back/app/retrieval/key_pool.py:152

_get_cooldown_seconds() reads an arbitrary integer from environment variable <PROVIDER>_KEY_COOLDOWN_SECONDS with no maximum bound. An operator misconfiguration (or env-var injection) can set this to MAX_INT, making all cool-downs permanent and effectively disabling key rotation permanently after the first failure.

**Recommendation:** Clamp the cooldown value to a sensible maximum (e.g., 30 days = 2592000 seconds). Log a warning if the configured value exceeds the maximum and clamp silently.

**Refs:** CWE-400, A05:2021

### [P2] thermia-back/app/retrieval/key_pool.py:353

SHA-256 is used to produce a short 8-hex-char log identifier for API keys (_hash_key). Truncating to 8 hex characters (32 bits) yields a trivially brute-forceable identifier: an attacker with log access can enumerate all known Cohere/Groq key formats and match hashes in seconds. This identifier provides false confidence about key identity confidentiality.

**Recommendation:** Use a keyed HMAC (e.g., HMAC-SHA256 with a server-side log-salt stored outside the pool) truncated to 8 chars, or simply log the key index only. The primary goal is distinguishing keys in logs, not proving key identity.

**Refs:** CWE-327, A02:2021

### [P2] thermia-back/app/retrieval/llm.py:83

Prompt injection partial mitigation: a delimiter comment ('---') and an instruction to ignore embedded document instructions are included in the HumanMessage. However, the context string (built from database-retrieved legal text) is concatenated without sanitisation into the same message. Crafted content stored in the database (e.g., injected during ingest from a malicious .md file in the corpus) can override the delimiter and inject instructions to the LLM.

**Recommendation:** Treat LLM output as untrusted: validate the parsed JSON strictly against the expected schema (string resumen, arrays of strings) before returning it. Add output-length limits. Consider using Groq's structured-output / JSON mode to constrain the response format at the API level.

**Refs:** CWE-20, A03:2021

### [P2] thermia-back/scripts/ingest.py:53

The repository is cloned from an external GitHub URL (_REPO_URL = 'https://github.com/legalize-dev/legalize-es') and then checked out to a pinned commit hash. The clone itself uses HTTPS without any certificate pinning or checksum verification on the clone step. A DNS-spoofing or MitM attacker between the ingest host and GitHub can serve a different repository prior to the checkout step; gitpython's Repo.clone_from does not validate the remote certificate chain in all configurations.

**Recommendation:** Verify that the gitpython/libgit2 TLS chain-of-trust is enforced (GIT_SSL_NO_VERIFY must not be set). After checkout, compute and compare a SHA-256 hash of all ingested .md files against a known-good manifest to detect tampering. Log a clear error if any file hash mismatches.

**Refs:** CWE-427, A08:2021

### [P3] thermia-back/.env.example:9

.env.example documents SSH_PASSWORD and DB_PASSWORD as plain-text environment variables with no reference to secrets management. Developers who copy this file and store it as .env commit it into version control or leave it on disk. There is no .gitignore entry documented in the example itself.

**Recommendation:** Add a prominent comment at the top of .env.example referencing the project .gitignore rule for .env. Consider documenting an alternative using a secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault) for production SSH and DB credentials rather than flat env vars.

**Refs:** CWE-312, A02:2021

### [P3] thermia-back/app/retrieval/embedder.py:33

_RETRY_DELAYS = (10, 30, 60) produces a worst-case in-key retry wall time of 100 seconds per key before rotating. With N keys this is 100*N seconds of total blocking time on a synchronous caller thread, with no overall deadline. Under adversarial rate-limit flooding this creates a denial-of-service amplification risk: a single request can hold a thread blocked for up to ~5 minutes with 3 keys.

**Recommendation:** Add a per-request total timeout that is enforced across all retries and rotations. Expose this as COHERE_REQUEST_TIMEOUT_SECONDS. Raise a timeout error and return HTTP 503 to the client rather than blocking indefinitely.

**Refs:** CWE-400, A05:2021

## Simplifier

Status: `complete`

### [P2] thermia-back/app/retrieval/embedder.py:127

Post-rotation embed call duplicates the in-loop call body verbatim (lines 127-134 mirror lines 104-111)

**Recommendation:** Refactor get_query_embedding to use a single retry loop that covers both the in-key retries and the post-rotation attempt, eliminating the duplicated cohere_client.embed(...) call block after mark_failed.

**Pattern:** `pass-through-wrapper`

### [P2] thermia-back/scripts/ingest.py:315

generate_embeddings hand-rolls '429' / 'rate limit' detection instead of importing classify_failure from key_pool, duplicating logic already centralised there

**Recommendation:** Import classify_failure from app.retrieval.key_pool and replace the inline string check with classify_failure(exc) is not None to reuse the single authoritative implementation.

**Pattern:** `dead-code`

### [P3] thermia-back/tests/retrieval/test_key_pool.py:611

test_generate_embeddings_uses_pool_singleton calls sys.path.insert() again (line 611) even though the module-level sys.path.insert at line 15 already adds the same path

**Recommendation:** Remove the redundant sys.path.insert call inside the test method; the module-level insert is sufficient.

**Pattern:** `dead-code`

### [P3] thermia-back/tests/retrieval/test_key_pool.py:628

test_ingest_main_uses_get_cohere_pool uses a 20-line AST parse + walk to assert that the string 'COHERE_API_KEY' does not appear in main() — a plain string-contains check on the function source would be equivalent

**Recommendation:** Replace the ast.parse / ast.walk block with a simple substring assertion: assert 'COHERE_API_KEY' not in ingest_source[ingest_source.index('def main'):]. This removes ~15 lines of over-engineered static analysis for a string containment test.

**Pattern:** `over-validation`

## Files with most findings

- `thermia-back/app/retrieval/key_pool.py` — 7 findings (code-quality: 4, security: 3)
- `thermia-back/app/retrieval/embedder.py` — 5 findings (code-quality: 1, security: 3, simplifier: 1)
- `thermia-back/tests/retrieval/test_key_pool.py` — 5 findings (code-quality: 3, simplifier: 2)
- `thermia-back/scripts/ingest.py` — 4 findings (code-quality: 2, security: 1, simplifier: 1)
- `thermia-back/app/main.py` — 2 findings (security: 2)
- `thermia-back/app/retrieval/llm.py` — 1 findings (security: 1)
- `thermia-back/.env.example` — 1 findings (security: 1)
