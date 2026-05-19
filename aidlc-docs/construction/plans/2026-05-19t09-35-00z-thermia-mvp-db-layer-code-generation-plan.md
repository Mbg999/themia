# Code-Generation Plan: `db-layer`
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp
**Unit:** db-layer
**Layer:** 0 (no dependencies)
**Plan sub-stage:** plan
**Date:** 2026-05-19

---

## Environment Notes

[Env] python3 3.14.5 found at /Users/miguel.belmonte/homebrew/bin/python3 — USE existing installation
[Env] pip3 26.1.1 found at /Users/miguel.belmonte/homebrew/bin/pip3 — USE existing installation
[Env] thermia-back/ does NOT exist — create from scratch
[Env] CodeGraph indexed 39 files; no existing `get_engine` or `Document` class symbols — no duplicates detected

---

## CodeGraph Pre-Flight

- Duplicate check for `get_engine`: no results — safe to generate
- Duplicate check for `Document` (class): no results — safe to generate
- Blast-radius check: N/A (no existing symbols being modified)

---

## Task Checkboxes

### DB-T1 — Create `thermia-back/` project skeleton

**Slice 1.1 — Directory scaffold**

- [x] Create `thermia-back/app/`, `thermia-back/app/db/`, `thermia-back/scripts/`, `thermia-back/tests/`, `thermia-back/alembic/`
- [x] Create `thermia-back/app/__init__.py`, `thermia-back/app/db/__init__.py`, `thermia-back/tests/__init__.py`
- [x] Create `thermia-back/requirements.txt` with pinned versions:
  ```
  fastapi>=0.115.0
  uvicorn[standard]>=0.32.0
  sqlalchemy>=2.0.0
  alembic>=1.14.0
  pgvector>=0.3.0
  psycopg2-binary>=2.9.0
  sshtunnel>=0.4.0
  python-dotenv>=1.0.0
  pytest>=8.0.0
  pytest-mock>=3.14.0
  ```

**Slice 1.2 — FastAPI stub**

- [x] Write `thermia-back/app/main.py` with a minimal FastAPI app (`GET /health` returns `{"status": "ok"}`)
- [x] Write `thermia-back/app/config.py` with `python-dotenv` load; exposes `THERMIA_ENV`, `DATABASE_URL`, `SSH_HOST`, `SSH_USER`, `SSH_KEY_PATH`, `SSH_REMOTE_BIND_PORT` from `os.environ`
- [x] Write `thermia-back/.env.example` listing all env vars (no real values)

**Acceptance Criteria:**
- `thermia-back/` exists with `app/`, `scripts/`, `tests/`, `alembic/` directories
- `requirements.txt` present with all 8+ packages
- `uvicorn app.main:app` starts without import errors
- No hardcoded secrets anywhere

**TDD notes:**
- Slice 1.2 test: import `app.main` succeeds; `GET /health` returns `{"status": "ok"}` (using FastAPI `TestClient`)

---

### DB-T2 — Write `Document` SQLAlchemy model

**Slice 2.1 — ORM model with Vector(1024)**

- [x] Write `thermia-back/app/db/models.py`:
  - `Base = declarative_base()`
  - `Document` class with columns:
    - `id`: `UUID`, primary_key=True, server_default=`gen_random_uuid()`
    - `content`: `Text`, nullable=False
    - `embedding`: `Vector(1024)` from `pgvector.sqlalchemy`
    - `tsvector`: `TSVECTOR` (via `sqlalchemy.dialects.postgresql.TSVECTOR`)
    - `metadata_`: `JSONB` (column named `metadata` in DB), `server_default='{}'`
  - `__tablename__ = "documents"`

**Acceptance Criteria:**
- Model imports without error (no DB connection needed)
- `embedding` column uses `pgvector.sqlalchemy.Vector(1024)`
- `metadata_` uses `JSONB`, mapped to column name `metadata`
- `id` uses `gen_random_uuid()` as server_default

**TDD notes:**
- Test: instantiate `Document(content="test", embedding=[0.0]*1024)` without error
- Test: `Document.__table__.c.embedding.type` is an instance of `Vector` with `dim == 1024`
- Test: `Document.__table__.c.id.primary_key is True`
- Test: `Document.__table__.c['metadata'].type.__class__.__name__ == 'JSONB'`

---

### DB-T3 — Initialize Alembic; write initial migration

**Slice 3.1 — Alembic scaffold**

- [x] Run `alembic init thermia-back/alembic` (or create structure manually)
- [x] Edit `thermia-back/alembic/env.py`:
  - Import `Base` from `app.db.models`
  - Set `target_metadata = Base.metadata`
  - Read `DATABASE_URL` from environment for online migrations
- [x] Edit `thermia-back/alembic.ini` to point `script_location = alembic`; `sqlalchemy.url` reads from env

**Slice 3.2 — Initial migration script**

- [x] Write `thermia-back/alembic/versions/0001_initial.py`:
  - `upgrade()`: `CREATE EXTENSION IF NOT EXISTS vector`, `CREATE TABLE documents (...)`, create `ivfflat` index on `embedding`, create `GIN` index on `tsvector`
  - `downgrade()`: `DROP TABLE documents`, `DROP EXTENSION vector`
- [ ] Column DDL in migration:
  - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
  - `content TEXT NOT NULL`
  - `embedding vector(1024)`
  - `tsvector tsvector`
  - `metadata JSONB DEFAULT '{}'`

**Acceptance Criteria:**
- `alembic upgrade head` applies cleanly on a fresh DB with pgvector
- `alembic downgrade base` reverts cleanly
- `\d documents` shows all 5 columns with correct types
- ivfflat index present on `embedding` column
- GIN index present on `tsvector` column

**TDD notes:**
- Alembic migration correctness is verified by inspection of the generated SQL (offline mode)
- Test: `alembic upgrade head --sql` produces SQL containing `CREATE TABLE documents` and `vector(1024)` (offline mode, no DB needed)
- The full round-trip (`upgrade head` / `downgrade base`) is in the Definition of Done and requires a real DB; unit test uses offline SQL generation

---

### DB-T4 — Write DB connection factory

**Slice 4.1 — Factory implementation**

- [x] Write `thermia-back/app/db/connection.py`:
  ```python
  def get_engine() -> Engine:
      """
      Returns a SQLAlchemy Engine.
      THERMIA_ENV=local  → SSHTunnelForwarder using SSH_* env vars; engine points to 127.0.0.1:<local_port>
      THERMIA_ENV=production → plain Engine from DATABASE_URL
      """
  ```
  - Read `THERMIA_ENV` from `os.environ` (default `"production"`)
  - `local` branch:
    - Read `SSH_HOST`, `SSH_USER`, `SSH_KEY_PATH`, `SSH_REMOTE_BIND_PORT` from env
    - Create `SSHTunnelForwarder(SSH_HOST, ssh_username=SSH_USER, ssh_pkey=SSH_KEY_PATH, remote_bind_address=("127.0.0.1", int(SSH_REMOTE_BIND_PORT)))`
    - Start tunnel, build engine to `postgresql+psycopg2://...@127.0.0.1:<local_bind_port>/thermia`
    - Expose `tunnel` as an attribute on the returned engine for lifecycle management
  - `production` branch:
    - Read `DATABASE_URL` from env
    - Return `create_engine(DATABASE_URL)`
  - All env var reads via `os.environ`; `python-dotenv` loaded in `config.py`

**Acceptance Criteria:**
- `THERMIA_ENV=local` creates `SSHTunnelForwarder` with all 4 SSH env vars
- `THERMIA_ENV=production` returns plain engine from `DATABASE_URL`
- No hardcoded connection strings

---

### DB-T5 — Unit tests: connection factory (both paths, mocked)

**Slice 5.1 — Test suite**

- [x] Write `thermia-back/tests/test_db.py`:

  **Test class: `TestGetEngineLocalPath`**
  - `test_local_creates_ssh_tunnel`: mock `sshtunnel.SSHTunnelForwarder`, set env `THERMIA_ENV=local` + SSH vars, call `get_engine()`, assert `SSHTunnelForwarder` called with correct args
  - `test_local_tunnel_is_started`: assert `tunnel.start()` was called
  - `test_local_engine_points_to_tunnel_local_port`: assert engine URL host is `127.0.0.1`

  **Test class: `TestGetEngineProductionPath`**
  - `test_production_uses_database_url`: mock `create_engine`, set env `THERMIA_ENV=production` + `DATABASE_URL=postgresql://user:pass@host/db`, call `get_engine()`, assert `create_engine` called with `DATABASE_URL`
  - `test_production_no_tunnel_created`: assert `SSHTunnelForwarder` NOT called

  **Test class: `TestGetEngineDefaults`**
  - `test_default_env_is_production`: when `THERMIA_ENV` not set, factory uses production path

  **Test for model:**
  - `test_document_model_columns`: verify `Document` has all 5 columns with correct types (no DB needed)
  - `test_embedding_dimension`: assert `Vector` dimension is 1024

**Acceptance Criteria:**
- `pytest tests/test_db.py` passes with 0 failures
- Factory module at 100% branch coverage (both `local` and `production` branches exercised)
- No real DB connection made in any test

---

## Cross-Cutting Concerns

- All env vars read via `os.environ` (loaded by `python-dotenv` in `config.py`); never hardcoded
- `Vector(1024)` dimension is the contract for all downstream units (`ingestion-pipeline`, `retrieval-api`)
- Alembic migration is the schema contract; downstream units must not re-create the table
- `get_engine()` is the sole DB connection entry point; SSH tunnel lifecycle (start/stop) is the caller's responsibility in production code

---

## Risk Notes

- PR-2 from execution plan: `Vector(1024)` in `DB-T2` and the migration in `DB-T3` are the hard contract. Any dimension mismatch breaks all of L1. The test in Slice 5.1 (`test_embedding_dimension`) guards this.
- `SSHTunnelForwarder.local_bind_port` is only available after `tunnel.start()` — the factory must call `start()` before reading the port to build the engine URL.

---

## File Manifest (to be created)

| File | Kind | Task |
|------|------|------|
| `thermia-back/requirements.txt` | config | DB-T1 |
| `thermia-back/.env.example` | config | DB-T1 |
| `thermia-back/app/__init__.py` | source | DB-T1 |
| `thermia-back/app/main.py` | source | DB-T1 |
| `thermia-back/app/config.py` | source | DB-T1 |
| `thermia-back/app/db/__init__.py` | source | DB-T1 |
| `thermia-back/app/db/models.py` | source | DB-T2 |
| `thermia-back/app/db/connection.py` | source | DB-T4 |
| `thermia-back/alembic.ini` | config | DB-T3 |
| `thermia-back/alembic/env.py` | source | DB-T3 |
| `thermia-back/alembic/script.py.mako` | config | DB-T3 |
| `thermia-back/alembic/versions/0001_initial.py` | source | DB-T3 |
| `thermia-back/tests/__init__.py` | test | DB-T5 |
| `thermia-back/tests/test_db.py` | test | DB-T5 |
| `thermia-back/scripts/.gitkeep` | config | DB-T1 |

---

## Approval Gate

This plan is submitted for human review. Upon approval the code-generator will be re-spawned to execute Sub-stage 2 (Generate).
