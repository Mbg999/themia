# Thermia Backend — Build Instructions (db-layer)

Run ID: 2026-05-19t09-35-00z-thermia-mvp  
Unit: db-layer  
Date: 2026-05-19

## Prerequisites

- Python 3.11+ (tested on 3.14.5)
- PostgreSQL VPS accessible via SSH tunnel (for local env) or direct URL (for production)
- SSH credentials for `THERMIA_ENV=local` migrations

## 1. Create and activate virtual environment

```bash
cd thermia-back/
python3 -m venv .venv
source .venv/bin/activate
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

**Note**: `requirements.txt` pins `paramiko<3` because `sshtunnel 0.4.0` references
`paramiko.DSSKey` which was removed in paramiko 3.x. This pin is required.

## 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in:
# - THERMIA_ENV=local  (for SSH tunnel) or production (for direct URL)
# - SSH_HOST, SSH_USER, SSH_PASSWORD, SSH_REMOTE_BIND_PORT  (local only)
# - DATABASE_URL  (production only)
```

## 4. Run unit tests (no DB required)

```bash
.venv/bin/pytest tests/test_db.py -v
```

Expected: 9 passed.

## 5. Apply database migration (requires live credentials)

Verify env loads correctly:
```bash
.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('THERMIA_ENV:', os.environ.get('THERMIA_ENV'))"
```

Apply migration:
```bash
.venv/bin/alembic upgrade head
```

Check current revision:
```bash
.venv/bin/alembic current
```

Expected output: `0001 (head)`

## Architecture notes

- `alembic/env.py` uses `app.db.connection.get_engine()` for online migrations.
  This ensures the SSH tunnel is opened before connecting when `THERMIA_ENV=local`.
- `SSHTunnelForwarder` is called with `allow_agent=False, host_pkey_directories=[]`
  to use password-only auth and avoid scanning `~/.ssh/` for key files.
- The tunnel is explicitly stopped in a `finally` block after migrations complete.
