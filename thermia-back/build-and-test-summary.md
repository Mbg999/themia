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
| TestAnalyzeLegalGuard | 2 | Empty PDF and non-legal PDF return 422 with Spanish message |
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
