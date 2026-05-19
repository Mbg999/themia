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
