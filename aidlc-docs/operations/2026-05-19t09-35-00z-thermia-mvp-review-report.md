# Code Review Report

Run: `2026-05-19t09-35-00z-thermia-mvp`
Reviewers: code-quality, security, performance, simplifier

## Summary

| Severity | code-quality | security | performance | simplifier | Total |
|---|---|---|---|---|---|
| P0 | 0 | 5 | 2 | 1 | 8 |
| P1 | 2 | 6 | 4 | 2 | 14 |
| P2 | 17 | 3 | 3 | 3 | 26 |
| P3 | 8 | 0 | 0 | 1 | 9 |

_Total findings across all reviewers:_ **57**

---

## Code Quality

Status: `complete`

### [P1] thermia-back/app/retrieval/embedder.py:25

`get_query_embedding` has no retry or error handling for Cohere API calls, unlike `generate_embeddings` in `ingest.py` which has full retry-with-backoff. Query-time embedding calls will fail on rate limits (429) during peak usage, returning 500 errors to users.

**Recommendation:** Add retry logic matching `ingest.py`'s `_EMBED_RETRY_DELAYS` pattern: catch cohere-specific exceptions, retry with exponential backoff on 429/rate-limit errors.

**Axis:** correctness

### [P1] thermia-back/scripts/ingest.py:452

Bare `except Exception` catches ALL exceptions including `KeyboardInterrupt` and `SystemExit`. A Ctrl+C during ingestion will be silently swallowed and processing continues. Also hides real bugs making debugging difficult.

**Recommendation:** Catch specific exceptions or re-raise `KeyboardInterrupt`. Add `logger.exception()` to capture full traceback on errors.

**Axis:** correctness

### [P2] thermia-back/Dockerfile:13

`COPY . .` copies the entire project directory including tests/, `__pycache__/`, `.env` (with secrets), `.pytest_cache/`, and other dev artifacts. No `.dockerignore` file exists.

**Recommendation:** Add a `.dockerignore` excluding `__pycache__/`, `*.pyc`, `.env`, `.pytest_cache/`, `tests/`, `.git/`.

**Axis:** maintainability

### [P2] thermia-back/app/config.py:32

`API_KEY` is an ambiguous config name that overlaps with `COHERE_API_KEY` and `GROQ_API_KEY`. Its purpose (FastAPI bearer auth) is not obvious from the name.

**Recommendation:** Rename to `AUTH_API_KEY` or `FASTAPI_AUTH_KEY` for clarity.

**Axis:** design

### [P2] thermia-back/app/db/connection.py:37

Uses dict bracket access (`os.environ[key]`) which raises `KeyError` with no context. `config.py` defines defaults but `connection.py` bypasses them.

**Recommendation:** Use `os.environ.get()` with explicit guard messages. e.g. `if not ssh_host: raise ValueError('SSH_HOST is required when THERMIA_ENV=local')`.

**Axis:** correctness

### [P2] thermia-back/app/db/connection.py:57

PostgreSQL URL built via f-string with `db_user` and `db_password` that may contain URL-unsafe characters (`@`, `:`, `%`, `/`). Malformed URL will cause opaque connection failures.

**Recommendation:** Use `SQLAlchemy`'s `URL.create()` or `urllib.parse.quote_plus()` to safely encode credentials.

**Axis:** correctness

### [P2] thermia-back/app/main.py:17

`CORS_ORIGINS` re-read directly from `os.environ` instead of importing from `app.config`, duplicating the default value.

**Recommendation:** Import `CORS_ORIGINS` from `app.config` instead of reading `os.environ` directly.

**Axis:** maintainability

### [P2] thermia-back/app/main.py:56

The `/analyze` endpoint handles auth, file validation, PDF parsing, embedding, vector search, BM25 search, RRF fusion, context building, LLM analysis, and SSH tunnel lifecycle in ~70 lines with no unit-testable sub-steps.

**Recommendation:** Extract retrieval pipeline into a dedicated service class. The endpoint should only handle HTTP concerns.

**Axis:** design

### [P2] thermia-back/app/main.py:108

`query_text` truncated at 2000 characters, not tokens. Cohere has token limits, not character limits.

**Recommendation:** Use token-aware truncation with `tiktoken` (cl100k_base, matching `ingest.py`) or set a higher character limit with a warning log when truncation occurs.

**Axis:** correctness

### [P2] thermia-back/app/retrieval/embedder.py:12

`get_query_embedding` has zero test coverage. Unlike `generate_embeddings` which has dedicated tests, the query-time embedding is untested.

**Recommendation:** Add unit tests covering normal response, API error, rate-limited response, and empty text input.

**Axis:** testing

### [P2] thermia-back/app/retrieval/fusion.py:42

Deduplication by article key uses `id(doc)` as fallback when article is missing. Python's `id()` is unique per object instance per process — two `Document` objects for the same article in different result lists get different IDs and won't be deduplicated.

**Recommendation:** Use a stable fallback like `f'{source_file}|{law_id}|{hash(content[:100])}'`.

**Axis:** correctness

### [P2] thermia-back/app/retrieval/llm.py:30

`analyze_with_llm` has no direct tests. The JSON parsing error path is untested.

**Recommendation:** Add unit tests with mocked `ChatGroq` covering valid JSON, markdown-fenced JSON, non-JSON response, and partial response.

**Axis:** testing

### [P2] thermia-back/app/retrieval/llm.py:53

LLM model name `'llama-3.1-8b-instant'`, system prompt, and `temperature=0.0` are hardcoded. Changing them requires a code deploy.

**Recommendation:** Move model name and temperature to `config.py` (`GROQ_MODEL`, `GROQ_TEMPERATURE`).

**Axis:** maintainability

### [P2] thermia-back/scripts/ingest.py:452

Broad `except Exception` in the main ingestion loop silently skips files. Operators won't be alerted to partial failures.

**Recommendation:** Add a counter for failed files, emit a consolidated error summary at the end, and exit with non-zero code if any files failed.

**Axis:** maintainability

### [P2] thermia-back/tests/:1

No integration or end-to-end tests exist. All 51 backend + 16 frontend tests are unit tests with fully mocked dependencies.

**Recommendation:** Add integration tests: FastAPI `TestClient` exercising `/analyze` with mocked retrieval internals, and a contract test verifying the LLM response shape.

**Axis:** testing

### [P2] thermia-back/tests/test_ingestion.py:364

Test asserts `merged_obj.tsvector is not None` which passes even for a regular string. Does not verify the SQL expression nature of `tsvector`.

**Recommendation:** Strengthen to `isinstance(merged_obj.tsvector, ClauseElement)`.

**Axis:** testing

### [P2] thermia-front/src/app/analysis.service.spec.ts:39

Service tests only cover the happy path. No tests for HTTP error responses (4xx, 5xx), network failures, or timeout scenarios.

**Recommendation:** Add test cases for 401, 422, network error (status 0), and Observable error propagation.

**Axis:** testing

### [P2] thermia-front/src/app/app.ts:30

Non-PDF file selection silently clears the file without user feedback. The button stays disabled with no indication why.

**Recommendation:** Set error signal with `'Solo se aceptan archivos PDF.'` when non-PDF is selected.

**Axis:** correctness

### [P3] thermia-back/app/main.py:39

`_check_auth` uses `partition(' ')` and manual string comparison. Verbose but functional.

**Recommendation:** Simplify to `if not authorization or not authorization.startswith('Bearer '): raise...`

**Axis:** readability

### [P3] thermia-back/app/main.py:100

Lazy imports inside the `/analyze` endpoint break Python convention. Import errors only surface at endpoint invocation.

**Recommendation:** Move imports to module level or use `lifespan` startup event.

**Axis:** readability

### [P3] thermia-back/app/retrieval/fusion.py:38

`doc_map` typed as `dict[str, object]` instead of `dict[str, Document]` despite `Document` being imported.

**Recommendation:** Change type annotation to `dict[str, Document]`.

**Axis:** readability

### [P3] thermia-back/scripts/ingest.py:339

`uuid.NAMESPACE_URL` hardcoded as a literal UUID string instead of using the stdlib constant.

**Recommendation:** Replace with `from uuid import NAMESPACE_URL as _NS`.

**Axis:** readability

### [P3] thermia-back/tests/test_retrieval.py:35

`TestClient` constructed inside test methods rather than using a shared fixture.

**Recommendation:** Use a `conftest.py` session-scoped fixture.

**Axis:** readability

### [P3] thermia-front/src/app/app.html:65

Non-null assertion (`!`) on `result()` inside `@if (result())` block. Angular does not narrow types from `@if` guard.

**Recommendation:** Use `result()?.implicaciones_legales` or `@let r = result()`.

**Axis:** design

### [P3] thermia-front/src/app/app.routes.ts:1

Routes file exports empty array with `provideRouter()` already configured. Router infrastructure loaded unnecessarily.

**Recommendation:** Remove `provideRouter` from `app.config.ts` if no routing needed.

**Axis:** design

### [P3] thermia-front/src/app/app.ts:18

Optional constructor parameter with manual `inject()` fallback is unconventional Angular DI.

**Recommendation:** Use `private readonly analysisService = inject(AnalysisService)` at field level.

**Axis:** design

---

## Security

Status: `complete`

### [P0] thermia-back/Dockerfile:13

`COPY . .` includes `thermia-back/.env` in the Docker build context. Real secrets (Cohere, Groq, SSH, DB credentials) are baked into image layers and can be extracted by anyone who pulls the image.

**Recommendation:** Add `.dockerignore` excluding `.env`. Inject secrets at container runtime via `docker-compose` environment variables or a secrets manager. **Revoke and rotate ALL secrets currently in `.env`.**

**Refs:** CWE-312, OWASP A02:2021

### [P0] thermia-back/app/main.py:55

No rate limiting on any endpoint. The API key is exposed in the frontend JS bundle, so anyone can extract it and hammer `/analyze`, enabling cost exposure (Cohere/Groq billing), server DoS, and brute-force attacks.

**Recommendation:** Implement rate limiting using `slowapi`. `/analyze`: 5–10 req/min per IP. `/health`: 30 req/min.

**Refs:** CWE-307, OWASP A04:2021

### [P0] thermia-back/app/main.py:87

No file size limit. `await file.read()` loads the entire request body into memory with no cap. A multi-GB upload exhausts server RAM.

**Recommendation:** Reject uploads above 10 MB before reading. Check `Content-Length` header or use a streaming size guard.

**Refs:** CWE-770, OWASP A04:2021

### [P0] thermia-back/scripts/ingest.py:374

Ingestion pipeline clones `legalize-es` without pinning to a commit hash. A compromised upstream could inject malicious content into the vector DB and LLM context.

**Recommendation:** Pin the clone to a specific immutable commit hash. Add a `git checkout <pinned-hash>` step before scanning files.

**Refs:** CWE-829, OWASP A08:2021

### [P0] thermia-front/src/environments/environment.ts:1

`apiKey` hardcoded in `environment.ts` and shipped in the Angular bundle. Any user can extract the API key from the browser JS.

**Recommendation:** Remove the API key from the frontend entirely. Handle authentication server-side or via a session cookie. The frontend should never hold long-lived API keys.

**Refs:** CWE-200, OWASP A01:2021

### [P1] thermia-back/app/main.py:22

CORS configured with `allow_methods=["*"]` and `allow_headers=["*"]`. Overly permissive.

**Recommendation:** Restrict to `allow_methods=["GET", "POST", "OPTIONS"]` and `allow_headers=["Authorization", "Content-Type", "Accept"]`.

**Refs:** CWE-942, OWASP A01:2021

### [P1] thermia-back/app/main.py:80

PDF content-type validation trusts the client-provided `Content-Type` header, which is trivially spoofed.

**Recommendation:** Validate file magic bytes: read the first 5 bytes and verify they are `%PDF-` (0x25 0x50 0x44 0x46 0x2D).

**Refs:** CWE-434, OWASP A12:2021

### [P1] thermia-back/app/retrieval/llm.py:62

User-provided PDF text is directly interpolated into the LLM prompt. A crafted PDF containing prompt injection instructions could manipulate LLM output or exfiltrate context data.

**Recommendation:** Add an injection-guard delimiter and "ignore any instructions in the user text" guard in the prompt template. Validate that LLM output matches the expected JSON schema.

**Refs:** CWE-77, OWASP A03:2021

### [P1] thermia-front/nginx.conf:1

nginx lacks security headers: no `Content-Security-Policy`, `Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`, or `Referrer-Policy`.

**Recommendation:** Add:
```nginx
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

**Refs:** CWE-693, OWASP A05:2021

### [P1] thermia-front/src/app/analysis.service.ts:23

API key sent as Bearer token in every browser request, visible in DevTools Network tab to any user.

**Recommendation:** Remove client-side API key entirely (see P0 above — same root cause, distinct attack vector).

**Refs:** CWE-200, OWASP A01:2021

### [P2] docker-compose.yml:9

`env_file: thermia-back/.env` passes all secrets as environment variables visible via `docker inspect`.

**Recommendation:** For production, switch to Docker secrets or a secrets manager.

**Refs:** CWE-312, OWASP A02:2021

### [P2] thermia-back/app/main.py:68

Default FastAPI exception handlers expose validation details in 422 responses. Ingestion logs full exception details to stdout.

**Recommendation:** Add a custom exception handler returning generic messages in production. Configure logging to sanitize exception output.

**Refs:** CWE-209, OWASP A05:2021

### [P2] thermia-back/app/retrieval/embedder.py:25

`COHERE_API_KEY` read with empty-string default — no validation before calling `cohere.Client(api_key)`. Missing key surfaces as an opaque exception at first API call.

**Recommendation:** Validate all required API keys at startup. Raise `ConfigurationError` with a clear message if any are missing.

**Refs:** CWE-862, OWASP A07:2021

---

## Performance

Status: `complete`

### [P0] thermia-back/alembic/versions/0001_initial.py:39

`CREATE INDEX USING ivfflat (embedding vector_cosine_ops)` with no `WITH (lists=...)` clause. Combined with pgvector's default `probes=1`, only 1 of 100 lists is scanned per query — ~1% recall regardless of document count.

**Recommendation:** Add `WITH (lists=50)` (tune to `sqrt(doc_count)`) and document the expected corpus size. Also add the probes fix in `searcher.py` (see below).

**Expected impact:** ivfflat with default `lists=100` and `probes=1` yields ~1% ANN recall, making vector search nearly non-functional.

### [P0] thermia-back/app/retrieval/searcher.py:39

`SET LOCAL ivfflat.probes` is never set before the `ORDER BY <=>` query. pgvector default `probes=1` searches only 1 of 100 lists per query.

**Recommendation:** Add `session.execute(text('SET LOCAL ivfflat.probes = 10'))` inside the same `Session` transaction immediately before the ANN query. Rule of thumb: `probes = sqrt(lists)`.

**Complexity:** O(1) lists searched out of O(lists) available — effective recall ~1%

**Expected impact:** Vector search returns essentially random results — the most critical correctness issue in the retrieval pipeline.

### [P1] thermia-back/app/db/connection.py:27

`get_engine()` calls `create_engine()` unconditionally on every invocation. `main.py` calls `get_engine()` inside every `/analyze` request, rebuilding the connection pool per request.

**Recommendation:** Cache the engine as a module-level singleton (e.g. `functools.lru_cache` or a `_engine` module variable). For the SSH tunnel path, create once per tunnel lifetime.

**Expected impact:** TCP handshake + SSL negotiation overhead on every request instead of reusing pooled connections. ~50–200ms latency added under concurrent load.

### [P1] thermia-back/app/main.py:113

`vector_search` and `bm25_search` are called sequentially despite having no data dependency. Total DB latency = `latency(vector) + latency(bm25)`.

**Recommendation:** Run both concurrently: `vector_results, bm25_results = await asyncio.gather(loop.run_in_executor(None, vector_search, ...), loop.run_in_executor(None, bm25_search, ...))`.

**Expected impact:** At p95 ~50ms per query, sequential execution doubles DB latency contribution to ~100ms per `/analyze` call.

### [P1] thermia-back/app/retrieval/embedder.py:26

`cohere.Client(api_key)` instantiated on every `get_query_embedding` call. No embedding cache.

**Recommendation:** Module-level singleton client + `functools.lru_cache` keyed on query text to avoid redundant Cohere API calls for repeated identical documents.

**Expected impact:** Client construction overhead per request (~5–20ms). Identical queries each pay full Cohere API round-trip (~300–800ms) with no reuse.

### [P1] thermia-back/app/retrieval/llm.py:52

`ChatGroq` constructed without `request_timeout`. `llm.invoke()` is synchronous and blocking with no deadline. Groq API spikes can reach 60s+.

**Recommendation:** `ChatGroq(..., request_timeout=30)`. Wrap in `try/except TimeoutError` returning HTTP 503. Move synchronous call to `run_in_executor` to avoid blocking the async event loop.

**Expected impact:** A hung Groq call holds a FastAPI worker thread indefinitely. Under sustained load this exhausts the Starlette thread pool (default 40 threads).

### [P2] thermia-back/app/main.py:87

`await file.read()` → `io.BytesIO(pdf_bytes)` → pdfplumber buffer = three simultaneous in-memory copies of the PDF. No size guard before reading.

**Recommendation:** Reject uploads above 10 MB before reading. `if len(pdf_bytes) > 10 * 1024 * 1024: raise HTTPException(413, ...)`.

**Expected impact:** A 200 MB upload consumes ~600 MB of worker RAM per concurrent request.

### [P2] thermia-back/scripts/ingest.py:311

Fixed 1s inter-batch pause sized for Cohere trial tier. For 10,000 chunks: 200 batches × 1s = 199s of pure sleep regardless of tier.

**Recommendation:** Make delay configurable via `EMBED_INTER_BATCH_SLEEP` env var (default `1.0` for trial, `0.05` for paid).

**Expected impact:** On paid Cohere tier, current pause is ~200x more conservative than needed. Full ingest of 10k chunks: ~9 min vs ~45s.

### [P2] thermia-back/scripts/ingest.py:341

`session.merge()` called per-chunk in a loop — O(n) SQL round-trips (SELECT + INSERT/UPDATE per chunk).

**Recommendation:** Replace with `sqlalchemy.dialects.postgresql.insert().on_conflict_do_update()` for bulk upsert in a single statement per batch.

**Expected impact:** 50k chunks = 100k+ SQL statements per full ingest run.

---

## Simplifier

Status: `complete`

### [P0] thermia-back/scripts/ingest.py:409

Inside `main()`, line 406 assigns `Session = sessionmaker(bind=engine)`. Line 409 then imports `from sqlalchemy.orm import Session as _Session` to avoid overwriting it. The `_Session` alias is a band-aid over a silent name-collision trap — if dropped, `upsert_documents(Session, chunks)` would silently receive the ORM class instead of the factory.

**Recommendation:** Rename the sessionmaker instance to `session_factory = sessionmaker(bind=engine)`, pass `session_factory` to `upsert_documents`, and remove the `_Session` alias entirely.

**Pattern:** dead-code

### [P1] thermia-back/app/config.py:12

`config.py` exports 12 module-level constants but zero are imported by any downstream module — every consumer calls `os.environ.get()` directly. The module's only real work is the `load_dotenv()` side-effect.

**Recommendation:** Remove the 12 constants. Keep `config.py` as a one-liner (`load_dotenv()`) or inline `load_dotenv()` into `main.py` and delete `config.py`.

**Pattern:** dead-code

### [P1] thermia-back/app/main.py:17

`config.py` exports `CORS_ORIGINS` but `main.py` duplicates the `os.environ.get("CORS_ORIGINS", "http://localhost:4200")` call independently. Future changes to the default in `config.py` silently won't apply here.

**Recommendation:** If `config.py` constants are kept, import `CORS_ORIGINS` from it. If `config.py` is simplified, keep the `os.environ` call in `main.py` as the single definition.

**Pattern:** dead-code

### [P2] thermia-back/app/main.py:99

Deferred imports inside the endpoint body claim "keeps startup fast" but in a single-process Uvicorn app modules load exactly once on first request regardless of import placement. The deferred imports obscure endpoint dependencies and make the first request slow instead of startup.

**Recommendation:** Move all six imports to the top of `main.py`.

**Pattern:** pass-through-wrapper

### [P2] thermia-back/app/retrieval/__init__.py:1

Contains only a docstring listing submodules. No consumer imports from the package directly. Inconsistent with the already-empty `app/__init__.py` and `app/db/__init__.py`.

**Recommendation:** Delete the docstring content or delete the file entirely.

**Pattern:** dead-code

### [P2] thermia-front/src/app/app.routes.ts:3

`routes: Routes = []` wired into `provideRouter()` in a single-view SPA. Router module registered in the DI tree for no benefit — scaffold leftover.

**Recommendation:** Remove `app.routes.ts`. Remove `provideRouter(routes)` from `app.config.ts`. Add back when a second route is actually needed.

**Pattern:** future-proofing

### [P3] thermia-back/app/main.py:35

`_is_legal_text()` introduces an intermediate `lowered` variable to avoid calling `.lower()` twice, but the generator short-circuits on first match so `.lower()` is called once anyway.

**Recommendation:** Collapse to `return any(kw in text.lower() for kw in _LEGAL_KEYWORDS)`.

**Pattern:** dead-code

---

## Files with most findings

| File | code-quality | security | performance | simplifier | Total |
|---|---|---|---|---|---|
| `thermia-back/app/main.py` | 7 | 4 | 2 | 3 | **16** |
| `thermia-back/scripts/ingest.py` | 3 | 1 | 2 | 1 | **7** |
| `thermia-back/app/retrieval/embedder.py` | 2 | 1 | 1 | 0 | **4** |
| `thermia-back/app/retrieval/llm.py` | 2 | 1 | 1 | 0 | **4** |
| `thermia-back/app/db/connection.py` | 3 | 0 | 1 | 0 | **4** |
| `thermia-back/app/retrieval/fusion.py` | 2 | 0 | 0 | 0 | **2** |
| `thermia-front/src/app/app.ts` | 2 | 0 | 0 | 0 | **2** |
| `thermia-back/Dockerfile` | 1 | 1 | 0 | 0 | **2** |
| `thermia-back/app/config.py` | 1 | 0 | 0 | 1 | **2** |
| `thermia-front/src/app/app.routes.ts` | 1 | 0 | 0 | 1 | **2** |
| `thermia-back/alembic/versions/0001_initial.py` | 0 | 0 | 1 | 0 | **1** |
| `thermia-back/app/retrieval/searcher.py` | 0 | 0 | 1 | 0 | **1** |
| `thermia-front/nginx.conf` | 0 | 1 | 0 | 0 | **1** |
| `thermia-back/app/retrieval/__init__.py` | 0 | 0 | 0 | 1 | **1** |
| `thermia-front/src/environments/environment.ts` | 0 | 1 | 0 | 0 | **1** |
