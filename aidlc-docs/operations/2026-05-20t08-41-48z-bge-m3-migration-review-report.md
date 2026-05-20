# Code Review Report

Run: `2026-05-20t08-41-48z-bge-m3-migration`
Reviewers: code-quality, security, simplifier

## Summary

| Severity | code-quality | security | simplifier | Total |
|---|---|---|---|---|
| P0 | 0 | 0 | 0 | 0 |
| P1 | 3 | 3 | 0 | 6 |
| P2 | 7 | 3 | 8 | 18 |
| P3 | 3 | 2 | 2 | 7 |

_Total findings across all reviewers:_ **31**

## Code Quality

Status: `complete`

### [P1] ✅ FIXED — thermia-back/app/retrieval/embedder.py:41

_get_ollama_client() has a TOCTOU race: two threads can both see _ollama_client is None and build two clients simultaneously

**Recommendation:** Protect the check-and-rebuild block with a threading.Lock (module-level _client_lock). Acquire the lock before checking _ollama_client, build inside the lock, then release. This is the standard double-checked locking pattern for singleton creation.

**Axis:** correctness

### [P1] ✅ FIXED — thermia-back/app/retrieval/embedder.py:81

No validation of embedding dimensionality: if Ollama returns fewer than 1024 floats (e.g. wrong model loaded), the malformed vector is returned silently

**Recommendation:** After `return response["embeddings"][0]`, assert or check len == 1024 and raise a descriptive error such as `ValueError(f"Expected 1024-dim vector, got {len(vec)}")`. This turns a silent data corruption into a fast, diagnosable failure.

**Axis:** correctness

### [P1] ✅ FIXED — thermia-back/app/retrieval/embedder.py:93

raise last_exc when last_exc is None causes TypeError, not a domain exception

**Recommendation:** Guard the raise: assert last_exc is not None, "last_exc should never be None here" or restructure the loop so the exhaustion path cannot be reached with last_exc=None. Alternatively use `raise last_exc or RuntimeError('all retries exhausted')`.

**Axis:** correctness

### [P2] ✅ FIXED — thermia-back/app/retrieval/embedder.py:90

Trailing `continue` at the end of the except block is redundant and adds noise

**Recommendation:** Remove the `continue` statement; it is the last statement in the for-body and has no semantic effect. Its presence implies intent that is not present.

**Axis:** readability

### [P2] ✅ FIXED — thermia-back/scripts/ingest.py:66

_EMBED_INTER_BATCH_SLEEP is evaluated at module import time from os.environ; cannot be overridden via monkeypatch.setenv in tests without module reload

**Recommendation:** Read the env var inside generate_embeddings() at call time, or accept an optional parameter for the inter-batch sleep duration. This makes the behaviour controllable in tests and avoids the subtle import-time side-effect.

**Axis:** design

### [P2] ✅ FIXED — thermia-back/scripts/ingest.py:329

Final retry attempt failure is not logged before the exception propagates; observability gap for operators

**Recommendation:** Move the log.info call outside the `if attempt < _EMBED_RETRY_COUNT:` guard (or add a separate log.error after the retry loop at line 338) so that every failed attempt is visible in logs, not just the non-final ones.

**Axis:** maintainability

### [P2] ✅ FIXED — thermia-back/tests/retrieval/test_embedder.py:25

reset_embedder_singletons fixture mutates private module attributes by name; if the attribute names change the fixture silently becomes a no-op

**Recommendation:** Expose a reset() or _reset_client() helper in embedder.py, or use importlib.reload() in the fixture. Direct assignment to _ollama_client / _ollama_client_host couples tests to internal naming and makes refactoring silent-failure-prone.

**Axis:** testing

### [P2] ✅ FIXED — thermia-back/tests/retrieval/test_embedder.py:142

Comment on line 142 says 'we need to check isinstance' but the production code uses hasattr duck-typing, not isinstance; the comment is inaccurate and misleads reviewers

**Recommendation:** Update the comment to accurately describe the detection mechanism: 'Non-retryable check uses hasattr(exc, "status_code") — duck-typing, not isinstance.' Also remove the dead assignment `mock_ollama.ResponseError = Exception` on line 141 which is immediately overwritten by FakeResponseError on line 149.

**Axis:** readability

### [P2] ✅ FIXED — thermia-back/tests/test_ingestion.py:343

Class TestCohereEmbedding tests Ollama behaviour; the stale Cohere name creates confusion and will surface in any future grep for Cohere references

**Recommendation:** Rename to TestOllamaEmbedding (or TestGenerateEmbeddings). The 'git history continuity' rationale does not justify ongoing confusion for every future reader. Git log preserves history regardless of the class name.

**Axis:** maintainability

### [P2] ✅ FIXED — thermia-back/tests/test_ingestion.py:412

Class TestKeyRotation tests Ollama retry logic, not key rotation; the name is semantically wrong and misleads about what is being tested

**Recommendation:** Rename to TestGenerateEmbeddingsRetry or TestOllamaRetry. Same rationale as TestCohereEmbedding finding above.

**Axis:** maintainability

### [P3] ✅ FIXED — thermia-back/scripts/ingest.py:317

import ollama is deferred inside generate_embeddings() while embedder.py imports ollama at module level; the deferred import rationale (test isolation) is inconsistent across the codebase

**Recommendation:** Either move the import to the top of ingest.py (accepting tests must patch 'scripts.ingest.ollama') for consistency with embedder.py, or add a comment explicitly justifying the per-function deferred import strategy in ingest.py.

**Axis:** design

### [P3] ✅ FIXED — thermia-back/tests/retrieval/test_embedder.py:45

import app.retrieval.embedder as mod is placed inside the `with patch(...)` context block in test_default_host and test_custom_host; this is misleading because the module is already cached from the autouse fixture

**Recommendation:** Move the import to the top of each test method (before the with block) or to a module-level import. The placement inside the patch context implies that the import should pick up the patch, but Python's module cache means it does not.

**Axis:** readability

### [P3] ✅ FIXED — thermia-back/tests/retrieval/test_key_pool.py:285

rotation_count is collected in test_50_concurrent_threads_single_rotation but never asserted; it is dead test scaffolding

**Recommendation:** Either assert on rotation_count (e.g. assert rotation_count >= 1 to confirm at least one thread triggered a rotation) or remove the variable and rotation_lock entirely to simplify the test.

**Axis:** testing

## Security

Status: `complete`

### [P1] ✅ FIXED — thermia-back/app/retrieval/embedder.py:40

OLLAMA_HOST env var accepted without scheme or host validation, enabling SSRF to internal network services.

**Recommendation:** Validate OLLAMA_HOST at application startup: parse the URL with urllib.parse.urlparse, assert scheme is 'https' (or 'http' only for 127.0.0.1/localhost), and raise RuntimeError if the check fails.

**Refs:** CWE-918, A10:2021

### [P1] ✅ FIXED — thermia-back/app/retrieval/embedder.py:83

No HTTP timeout is set on the ollama.Client — unresponsive server exhausts FastAPI thread-pool workers.

**Recommendation:** Pass an explicit timeout when constructing ollama.Client: ollama.Client(host=host, timeout=30.0). Apply the same timeout in ingest.py.

**Refs:** CWE-400, A05:2021

### [P1] ✅ FIXED — thermia-back/scripts/ingest.py:325

ingest.py called the module-level ollama.embed() function whose internal client is created at import time without URL validation — same SSRF risk as embedder.py.

**Recommendation:** Replace ollama.embed() with an explicit ollama.Client(host=validated_host).embed() call after dotenv is loaded.

**Refs:** CWE-918, A10:2021

### [P2] ✅ FIXED — thermia-back/.env.example:29

The default OLLAMA_HOST uses http:// with no warning that non-localhost deployments must use https://.

**Recommendation:** Add an inline comment stating that OLLAMA_HOST must use https:// for any non-localhost endpoint.

**Refs:** CWE-319, A02:2021

### [P2] ✅ FIXED — thermia-back/requirements.txt:13

ollama>=0.6.2 is an unbounded lower-bound pin with no upper-bound constraint.

**Recommendation:** Pin with a tighter constraint, e.g. 'ollama>=0.6.2,<1.0.0', and add ollama to CI dependency scanning (pip-audit / Dependabot).

**Refs:** CWE-1395, A06:2021

### [P2] ✅ FIXED — thermia-back/scripts/ingest.py:482

Exception objects are logged directly — ollama ConnectionError/ResponseError includes the full OLLAMA_HOST URL in str(), leaking internal endpoint to log aggregators.

**Recommendation:** Replace 'log.error(..., exc)' with 'log.error(..., type(exc).__name__)' for Ollama errors, or sanitize the exception message.

**Refs:** CWE-209, A09:2021

### [P3] ✅ FIXED — thermia-back/app/retrieval/embedder.py:22

OLLAMA_HOST defaults to http://localhost:11434 with no startup validation enforcing HTTPS for production. (Note: _validate_host() now runs at client-build time, not at application startup.)

**Recommendation:** Call _validate_host() at application startup (e.g. in main.py lifespan) rather than lazily at first embedding call.

**Refs:** CWE-547, A05:2021

### [P3] ✅ FIXED — thermia-back/scripts/ingest.py:66

EMBED_INTER_BATCH_SLEEP is read with float() at module load time before dotenv is loaded; a malformed value crashes at import time.

**Recommendation:** Move parsing inside main() after dotenv loading; add try/except with fallback to 1.0; clamp to 0.0–60.0 seconds.

**Refs:** CWE-20, A03:2021

## Simplifier

Status: `complete`

### [P2] ✅ FIXED — thermia-back/app/retrieval/embedder.py:27

Module docstring still describes host-tracking mechanism. Should be trimmed to: host source, model, retry strategy, security note.

**Recommendation:** Trim docstring; remove sentence about '_ollama_client is only written inside _get_ollama_client(), which rebuilds atomically based on the current OLLAMA_HOST value'.

**Pattern:** `future-proofing`

### [P2] ✅ FIXED — thermia-back/app/retrieval/embedder.py:29

_ollama_client_host is a second module-level variable kept solely to detect host changes. In production the host never changes.

**Recommendation:** Remove _ollama_client_host; simplify _get_ollama_client to rebuild only when _ollama_client is None. Tests reset only _ollama_client.

**Note:** Kept in P1 fix to support double-checked locking host comparison. Revisit after confirming tests pass without it.

**Pattern:** `future-proofing`

### [P2] ✅ FIXED — thermia-back/scripts/ingest.py:66 (duplicate)

_EMBED_INTER_BATCH_SLEEP env-override is a Cohere-era rate-limit knob; plain constant is sufficient.

**Recommendation:** Replace os.environ.get call with plain literal `_EMBED_INTER_BATCH_SLEEP = 1.0`.

**Pattern:** `future-proofing`

### [P2] ✅ FIXED — thermia-back/scripts/ingest.py:317 (duplicate)

'import ollama' deferred inside generate_embeddings() body; inconsistent with embedder.py module-level import.

**Recommendation:** Move to top-level imports. Tests patch 'ollama.Client' module-level and will continue to work.

**Pattern:** `future-proofing`

### [P2] ✅ FIXED — thermia-back/tests/test_ingestion.py:296

TestBuildEmbeddingText has 2 redundant tests (test_law_id_in_prefix, test_article_in_prefix) already covered by test_prefix_format.

**Recommendation:** Remove test_law_id_in_prefix and test_article_in_prefix.

**Pattern:** `dead-code`

### [P2] ✅ FIXED — thermia-back/tests/test_ingestion.py:343 (duplicate)

Class TestCohereEmbedding is a stale name.

**Recommendation:** Rename to TestOllamaEmbedding.

**Pattern:** `dead-code`

### [P2] ✅ FIXED — thermia-back/tests/test_ingestion.py:412 (duplicate)

Class TestKeyRotation is a stale name.

**Recommendation:** Rename to TestOllamaRetryBehaviour.

**Pattern:** `dead-code`

### [P2] ✅ FIXED — thermia-back/tests/test_ingestion.py:637

TestMainNoCohereReferences duplicates AST-based Cohere-absence checks already in TestIngestKeyPool (test_key_pool.py).

**Recommendation:** Remove the entire TestMainNoCohereReferences class from test_ingestion.py.

**Pattern:** `future-proofing`

### [P3] ✅ FIXED — thermia-back/app/retrieval/key_pool.py:1

Module docstring references ingest.py as a threading rationale; ingest.py no longer uses key_pool.

**Recommendation:** Update docstring: remove 'ingest.py is synchronous' bullet; update threading rationale to FastAPI Groq calls only.

**Pattern:** `dead-code`

### [P3] ✅ FIXED — thermia-back/tests/retrieval/test_embedder.py:23

reset_embedder_singletons fixture resets _ollama_client_host in setup and teardown; teardown reset is redundant; if _ollama_client_host is removed the reference breaks.

**Recommendation:** After resolving embedder.py:29, simplify fixture to reset only mod._ollama_client = None before yield; drop post-yield reset.

**Pattern:** `future-proofing`

## Files with most findings

- `thermia-back/app/retrieval/embedder.py` — 9 findings (code-quality: 4, security: 3, simplifier: 2)
- `thermia-back/scripts/ingest.py` — 8 findings (code-quality: 3, security: 3, simplifier: 2)
- `thermia-back/tests/test_ingestion.py` — 6 findings (code-quality: 2, simplifier: 4)
- `thermia-back/tests/retrieval/test_embedder.py` — 4 findings (code-quality: 3, simplifier: 1)
- `thermia-back/tests/retrieval/test_key_pool.py` — 1 findings (code-quality: 1)
- `thermia-back/requirements.txt` — 1 findings (security: 1)
- `thermia-back/.env.example` — 1 findings (security: 1)
- `thermia-back/app/retrieval/key_pool.py` — 1 findings (simplifier: 1)
