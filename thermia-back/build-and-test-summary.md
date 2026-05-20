# Thermia Backend — Build and Test Summary (db-layer)

Run ID: 2026-05-19t09-35-00z-thermia-mvp  
Unit: db-layer  
Date: 2026-05-19  
Status: NEEDS HUMAN (alembic blocked by invalid SSH credentials in .env)

---

## Unit Test Results

| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| tests/test_db.py | 9 | 9 | 0 | 0 |

All 9 unit tests pass. No DB connection required.

Warnings (non-blocking):
- `paramiko/pkey.py`: TripleDES deprecation warning (cosmetic, no functional impact with paramiko 2.12.0)

---

## Alembic Migration Result

| Step | Result | Detail |
|------|--------|--------|
| `alembic upgrade head` | BLOCKED | SSH authentication failed |
| `alembic current` | N/A — not reached | |

**Root cause**: SSH password authentication rejected by `pgdb.cvbooster.es` for user `themiauser`.  
The `.env` file contains an invalid `SSH_PASSWORD` value.

The SSH server is reachable (TCP port 22 open), the handshake completes, but paramiko logs:  
`Authentication (password) failed.`

**Action required**: Update `SSH_PASSWORD` in `thermia-back/.env` with the correct password for `themiauser@pgdb.cvbooster.es`.

---

## Code Defects Found and Fixed

Three defects were found and remediated during the build/test phase:

### Fix 1 — alembic/env.py bypassed SSH tunnel (critical)

- **What**: `alembic/env.py` read `DATABASE_URL` directly via `engine_from_config`, never calling `app.db.connection.get_engine()`. For `THERMIA_ENV=local`, the SSH tunnel was never opened, causing a connection failure to the placeholder host in `DATABASE_URL`.
- **Where**: `thermia-back/alembic/env.py` `run_migrations_online()`
- **Fix**: Replaced `engine_from_config(...)` with `from app.db.connection import get_engine; connectable = get_engine()`. Added `finally` block to stop the tunnel after migration.

### Fix 2 — paramiko 5.x incompatible with sshtunnel 0.4.0 (critical)

- **What**: `sshtunnel 0.4.0` references `paramiko.DSSKey` which was removed in paramiko 3.x. `paramiko 5.0.0` was installed, causing `AttributeError: module 'paramiko' has no attribute 'DSSKey'`.
- **Where**: `thermia-back/requirements.txt` (missing version pin)
- **Fix**: Added `paramiko<3` pin to `requirements.txt`. Installed `paramiko 2.12.0`.

### Fix 3 — SSH tunnel tried password-protected local key files (critical)

- **What**: `SSHTunnelForwarder` with default settings scanned `~/.ssh/` for key files and tried the local `id_rsa` (which requires a passphrase), causing `Password is required for key ~/.ssh/id_rsa` then connection failure before password auth could be retried cleanly.
- **Where**: `thermia-back/app/db/connection.py` `get_engine()`
- **Fix**: Added `allow_agent=False, host_pkey_directories=[]` to `SSHTunnelForwarder(...)`.
- **Test updated**: `tests/test_db.py::TestGetEngineLocalPath::test_local_creates_ssh_tunnel` `assert_called_once_with` updated to include the two new kwargs.

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| 9/9 unit tests pass | PASS |
| `alembic upgrade head` completes without error | BLOCKED — invalid SSH password in .env |
| `alembic current` shows `0001_initial (head)` | NOT REACHED |
| No secrets appear in output files | PASS |

---

## Files Modified

| File | Change |
|------|--------|
| `alembic/env.py` | Replaced `engine_from_config` with `get_engine()`; added tunnel cleanup |
| `app/db/connection.py` | Added `allow_agent=False, host_pkey_directories=[]` to `SSHTunnelForwarder` |
| `requirements.txt` | Added `paramiko<3` pin |
| `tests/test_db.py` | Updated `assert_called_once_with` in `test_local_creates_ssh_tunnel` to match new call signature |

---

# Thermia Backend — Build and Test Summary (ingestion-pipeline)

Run ID: 2026-05-19t12-00-00z-thermia-mvp
Unit: ingestion-pipeline
Date: 2026-05-19
Status: NEEDS HUMAN (all tests pass — awaiting human approval before proceeding)

---

## Environment Detection

| Item | Value |
|------|-------|
| Python runtime | `.venv/bin/python` — Python 3.14.5 (pre-existing, no install needed) |
| pip install (cohere, gitpython, tiktoken) | exit 0, no errors |
| cohere installed | 6.1.0 |
| gitpython installed | 3.1.50 |
| tiktoken installed | 0.13.0 |

---

## Unit Test Results

| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| tests/test_db.py | 9 | 9 | 0 | 0 |
| tests/test_ingestion.py | 26 | 26 | 0 | 0 |
| tests/test_retrieval.py | 16 | 16 | 0 | 0 |
| **Total** | **51** | **51** | **0** | **0** |

All 51 tests pass. Runtime: 0.76 s.

Warnings (non-blocking):
- `paramiko/pkey.py` and `paramiko/transport.py`: TripleDES deprecation warning from paramiko 2.x. Cosmetic only; no functional impact on tests.

---

## Static Validation

No `tsc`, `pyright`, or `eslint` config detected. Python static analysis not configured in this unit. Validator step: N/A (pure-Python project, no type-checker config file present).

---

## CLI Smoke Test

```
usage: ingest.py [-h] [--reset]

Thermia legal corpus ingestion pipeline.

options:
  -h, --help  show this help message and exit
  --reset     Truncate the documents table before ingesting.
```

Exit code: 0. Usage printed correctly. No import errors.

---

## CodeGraph Affected-Test Detection

`.codegraph/codegraph.db` not present in workspace. Full suite executed (fallback path).

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| `pip install cohere gitpython tiktoken` succeeds | PASS |
| 9/9 db-layer tests pass | PASS |
| 26/26 ingestion tests pass | PASS |
| 16/16 retrieval tests pass | PASS |
| 51/51 total tests pass | PASS |
| `ingest.py --help` prints usage, exit 0 | PASS |
| No test failures or errors | PASS |
| No coverage regressions (coverage not measured) | N/A |

---

## Files Added / Modified This Unit

| File | Change |
|------|--------|
| `scripts/ingest.py` | New — full ingestion CLI (13.3 KB) |
| `tests/test_ingestion.py` | New — 26 pytest tests for ingestion pipeline |
| `requirements.txt` | Appended: `cohere>=5.0.0`, `gitpython>=3.1.0`, `tiktoken>=0.7.0`, `pdfplumber>=0.11.0`, `langchain>=0.3.0`, `langchain-groq>=0.2.0`, `python-multipart>=0.0.12` |

---

# Thermia Backend — Build and Test Summary (retrieval-api)

Run ID: 2026-05-19t14-00-00z-thermia-mvp
Unit: retrieval-api
Date: 2026-05-19
Status: NEEDS HUMAN (all automated checks pass — awaiting approval to proceed)

---

## Environment Detection

| Tool | Version | Source |
|------|---------|--------|
| Python | 3.14.5 | `.venv/bin/python` (pre-existing) |
| pytest | 9.0.3 | `.venv` |
| pdfplumber | 0.11.9 | `.venv` (already installed, >=0.11.0 satisfied) |
| langchain | 1.3.1 | `.venv` (already installed, >=0.3.0 satisfied) |
| langchain-groq | 1.1.2 | `.venv` (already installed, >=0.2.0 satisfied) |
| python-multipart | 0.0.29 | `.venv` (already installed, >=0.0.12 satisfied) |

No new installs required — all four dependencies pre-satisfied.

---

## pip install result

```
.venv/bin/pip install -q pdfplumber langchain langchain-groq python-multipart
EXIT: 0  (all packages already satisfied, no download performed)
```

---

## Unit Test Results

| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| tests/test_db.py | 9 | 9 | 0 | 0 |
| tests/test_ingestion.py | 26 | 26 | 0 | 0 |
| tests/test_retrieval.py | 16 | 16 | 0 | 0 |
| **Total** | **51** | **51** | **0** | **0** |

All 51 tests pass. Runtime: 0.48 s.

Warnings (non-blocking):
- `paramiko/pkey.py` and `paramiko/transport.py`: TripleDES deprecation warnings (pre-existing, cosmetic only).

---

## Retrieval-API Test Coverage (test_retrieval.py — 16 tests)

| Test Class | Tests | Description |
|------------|-------|-------------|
| TestAnalyzeAuth | 2 | Bearer token enforcement — missing header → 401, wrong token → 401 |
| TestAnalyzeFileType | 1 | Non-PDF upload returns 422 |
| TestRRFFusion | 4 | RRF deduplication, top-N limit, rank ordering, formula correctness |
| TestBuildContext | 3 | Context string format, separator, empty-list edge case |
| TestVectorSearch | 2 | Returns list, calls DB execute |
| TestBM25Search | 2 | Returns list, calls DB execute |

---

## App Smoke Test

```
.venv/bin/python -c "from app.main import app; print('app loaded OK')"
app loaded OK
SMOKE_EXIT: 0
```

`app.main` imports cleanly. The `POST /analyze` endpoint is registered and the application object is fully initialised.

---

## Static Validation

No `pyright` / `mypy` configuration present. Python syntax validated implicitly by the import smoke test (exit 0).

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| `pip install` exits 0 | PASS |
| 51/51 tests pass (9 db + 26 ingestion + 16 retrieval) | PASS |
| `app loaded OK` smoke test | PASS |
| No secrets appear in output files | PASS |

---

## Files Added (retrieval-api unit)

| File | Description |
|------|-------------|
| `app/retrieval/__init__.py` | Package init |
| `app/retrieval/embedder.py` | Cohere query embedding |
| `app/retrieval/searcher.py` | Vector and BM25 search against pgvector |
| `app/retrieval/fusion.py` | Reciprocal Rank Fusion (RRF) |
| `app/retrieval/context_builder.py` | Format ranked chunks into LLM context string |
| `app/retrieval/llm.py` | Groq LLM call (llama-3.3-70b-versatile) |
| `app/main.py` | Updated — added `POST /analyze` endpoint |
| `tests/test_retrieval.py` | 16 pytest unit tests for the retrieval pipeline |

---

# Thermia Frontend — Build and Test Summary (frontend)

Run ID: 2026-05-19t13-45-00z-thermia-mvp
Unit: frontend (thermia-front/)
Date: 2026-05-19
Status: NEEDS HUMAN (all automated checks pass — awaiting approval to proceed)

---

## Environment Detection

| Tool | Version | Source |
|------|---------|--------|
| Node.js | v22.20.0 | nvm (pre-existing, compatible) |
| npm | 10.9.3 | nvm / matches packageManager field |
| Vitest | 4.1.6 | node_modules (pre-installed) |
| Angular CLI | 21.2.11 | node_modules (pre-installed) |

No runtime installs required. `npm install` confirmed 471 packages up-to-date, 0 vulnerabilities.

---

## npm install result

```
npm install
471 packages audited in 902ms — up to date, 0 vulnerabilities
EXIT: 0
```

---

## Unit Test Results

| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| src/app/analysis.service.spec.ts | 5 | 5 | 0 | 0 |
| src/app/app.spec.ts | 11 | 11 | 0 | 0 |
| **Total** | **16** | **16** | **0** | **0** |

All 16 tests pass. Runtime: 928ms.

Test runner: Vitest v4.1.6, jsdom environment.

---

## Test Coverage (suites)

### analysis.service.spec.ts (5 tests)

| Test | Result |
|------|--------|
| should be created | PASS |
| should send POST to the /analyze endpoint | PASS |
| should set Authorization header with Bearer token | PASS |
| should send file as FormData field named "file" | PASS |
| should return typed Observable<AnalysisResponse> | PASS |

### app.spec.ts (11 tests)

| Test | Result |
|------|--------|
| button stays disabled when no file is selected | PASS |
| selecting a non-PDF file keeps button disabled | PASS |
| selecting a .pdf file enables the Analizar button | PASS |
| button is disabled while request is in flight | PASS |
| renders result data after successful response | PASS |
| shows 401 error message and re-enables button | PASS |
| shows 422 error message | PASS |
| shows 503 error message | PASS |
| shows network error (status 0) message | PASS |
| shows generic error message for unexpected status codes | PASS |
| all three result sections are accessible after success | PASS |

---

## Angular Production Build

```
npx ng build --configuration=production
EXIT: 0
```

| Chunk | Raw size | Transfer size |
|-------|----------|---------------|
| main-A3ROLOKF.js | 224.39 kB | 60.77 kB |
| styles-5INURTSO.css | 0 bytes | 0 bytes |

Build time: 2.404 s. Output: `thermia-front/dist/thermia-front/`.

WARNING (non-blocking): `src/app/app.scss` exceeded budget — 4.99 kB vs 4.00 kB limit (+990 bytes). This is a size-budget advisory, not a TypeScript or compilation error. Build exits 0.

---

## Static Validation

TypeScript is validated implicitly by `ng build --configuration=production`. The build completed without type errors (exit 0). No standalone `tsc --noEmit` config detected beyond angular.json.

---

## CodeGraph Affected-Test Detection

`.codegraph/codegraph.db` not present in workspace. Full suite executed (fallback path).

---

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| `npm install` exits 0, 0 vulnerabilities | PASS |
| 16/16 Vitest tests pass | PASS |
| `ng build --configuration=production` exits 0 | PASS |
| No TypeScript compilation errors | PASS |
| No test failures or errors | PASS |

---

## Files Added / Modified (frontend unit)

| File | Description |
|------|-------------|
| `src/environments/environment.ts` | Development environment config (apiUrl, apiKey) |
| `src/environments/environment.prod.ts` | Production environment config |
| `src/app/analysis.service.ts` | Angular service — HTTP POST to /analyze with Bearer auth |
| `src/app/app.ts` | Root component — file selection, loading state, error handling, result display |
| `src/app/app.html` | Component template |
| `src/app/app.scss` | Component styles |
| `src/app/analysis.service.spec.ts` | 5 unit tests for AnalysisService |
| `src/app/app.spec.ts` | 11 unit tests for App component logic |
| `vitest.config.ts` | Vitest configuration (jsdom, globals, coverage) |
| `vitest-setup.ts` | Angular TestBed + BrowserTestingModule bootstrap |
| `package.json` | Added test / test:watch / test:coverage scripts; added vitest + jsdom devDependencies |

---

# Thermia — Build and Test Summary (docker-infra)

Run ID: 2026-05-19t16-00-00z-thermia-mvp
Unit: docker-infra
Date: 2026-05-19
Status: NEEDS HUMAN (all checks pass with advisories — awaiting human approval)

---

## Environment Detection

| Tool | Version | Status |
|------|---------|--------|
| docker | 27.3.1 | present |
| docker compose plugin | not installed | `docker compose` subcommand unavailable |
| docker-compose (standalone) | not installed | N/A |
| nginx | present | `/Users/miguel.belmonte/homebrew/bin/nginx` |
| Docker daemon | not running | `unix:///var/run/docker.sock` unreachable |

---

## Step 1 — docker-compose.yml Syntax Validation

`docker compose config --quiet` failed: the Docker Compose CLI plugin is not installed (Docker 27.3.1 present; `docker compose` subcommand absent; standalone `docker-compose` also absent).

Fallback used: Python `yaml.safe_load()` structural parse — EXIT 0, valid YAML.

Manual schema review (Compose Spec):
- No `version:` key — correct for Compose Spec format.
- Both services (`thermia-back`, `thermia-front`) have valid `build.context`, `build.dockerfile`, `ports`, `restart` keys.
- `env_file: thermia-back/.env` — relative path from project root, correct for Compose.
- `depends_on: thermia-back` in `thermia-front` — correct syntax.

Result: PASS (advisory: install `docker-compose-plugin` or Docker Desktop to run `docker compose config --quiet` for full schema validation).

---

## Step 2 — Dockerfile Lint (hadolint)

Docker daemon not running — `hadolint` via `docker run` unavailable. Manual lint review applied (rules DL1000–DL4006).

### thermia-back/Dockerfile

| Rule | Finding | Result |
|------|---------|--------|
| DL3002 | `USER appuser` applied before `CMD` — no root at runtime | OK |
| DL3008 | No `apt-get` calls | N/A |
| DL3013 | `pip install --no-cache-dir` used | OK |
| DL3042 | No pip cache left behind | OK |
| Layer order | `requirements.txt` copied before source — correct caching | PASS |

No errors. No warnings.

### thermia-front/Dockerfile

| Rule | Finding | Result |
|------|---------|--------|
| DL3016 | `npm ci` used, not `npm install` | OK |
| DL3059 | Multi-stage build (node:20-alpine + nginx:alpine) | OK |
| DL3002 | Stage 2 runs as default nginx user (acceptable for nginx:alpine) | OK |
| Layer order | `package.json` / `package-lock.json` copied before source | PASS |
| Output path | `dist/thermia-front/browser` matches Angular default output | PASS |
| nginx config | Copied to `/etc/nginx/conf.d/default.conf` — correct for nginx:alpine | PASS |

No errors. No warnings.

Step result: PASS (manual review). Advisory: run `docker run --rm -i hadolint/hadolint < thermia-back/Dockerfile` when Docker daemon is available to confirm.

---

## Step 3 — nginx.conf Syntax

Direct `nginx -t -c thermia-front/nginx.conf`: failed with `"server" directive is not allowed here`. Expected — the file is a bare `server {}` block for `/etc/nginx/conf.d/default.conf` (included inside `http {}` by nginx's parent config), not a standalone top-level config.

Wrapped test (`events {} http { <nginx.conf> }`): `nginx: the configuration file ... syntax is ok` — EXIT 0.

DNS check: `host not found in upstream "thermia-back"` without substitution — expected; `thermia-back` resolves only inside Docker's network at runtime.

Result: PASS — syntax is correct and correctly scoped for `conf.d` inclusion.

---

## Step 4 — .gitignore Protects .env Files

| File | Exit code | Matched rule | Result |
|------|-----------|-------------|--------|
| `thermia-back/.env` | 0 (ignored) | `thermia-back/.gitignore:1:.env` | PASS |
| `.env` (project root) | 0 (ignored) | `.gitignore:8:.env` | PASS |

---

## Step 5 — .env.example NOT Ignored

| File | Exit code | Result |
|------|-----------|--------|
| `thermia-back/.env.example` | 1 (not ignored) | PASS |

---

## Acceptance Criteria Status

| Criterion | Status | Notes |
|-----------|--------|-------|
| docker-compose.yml valid YAML | PASS | Python yaml.safe_load exit 0 |
| docker-compose.yml Compose Spec schema correct | PASS | Manual review |
| `docker compose config --quiet` | ADVISORY | Plugin not installed |
| thermia-back/Dockerfile lint clean | PASS | Manual hadolint-rule review |
| thermia-front/Dockerfile lint clean | PASS | Manual hadolint-rule review |
| nginx.conf syntax valid | PASS | Wrapped nginx -t exit 0 |
| `thermia-back/.env` git-ignored | PASS | thermia-back/.gitignore match |
| `.env` (root) git-ignored | PASS | .gitignore:8 match |
| `thermia-back/.env.example` NOT ignored | PASS | git check-ignore exit 1 |

---

## Files Delivered (docker-infra unit)

| File | Description |
|------|-------------|
| `thermia-back/Dockerfile` | Python 3.12-slim, non-root user, layer-cached deps |
| `thermia-front/Dockerfile` | Multi-stage: node:20-alpine build + nginx:alpine serve |
| `thermia-front/nginx.conf` | SPA fallback, gzip, proxy /analyze and /health to back-end |
| `docker-compose.yml` | Compose Spec — both services, env_file, depends_on, restart |
| `thermia-front/.env.example` | Frontend environment template |
| `README.md` | Updated with Docker Compose quick-start instructions |
| `.gitignore` (root) | Updated to protect .env files |

---

## Advisories (non-blocking)

1. **docker compose plugin not installed** — `docker compose config --quiet` could not be executed. Install `docker-compose-plugin` (Linux) or upgrade Docker Desktop (macOS) to enable full schema validation.
2. **hadolint not run** — Docker daemon was offline. Run `docker run --rm -i hadolint/hadolint < thermia-back/Dockerfile` (and the front Dockerfile) once the daemon is available.
3. **nginx upstream DNS advisory** — `nginx -t` with the `thermia-back` upstream name will fail on the host OS (not resolvable outside Docker networking). This is expected and not a defect.
