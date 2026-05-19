# Unit Spec: `db-layer`
**Run ID:** 2026-05-19t09-35-00z-thermia-mvp
**Layer:** 0 | **Dependencies:** none

---

## Purpose
Establish the entire data foundation for Thermia: PostgreSQL schema with pgvector, SQLAlchemy ORM model, Alembic migrations, and the environment-aware connection factory (local dev via SSH tunnel, production via direct URL).

## Responsibilities
- Create `thermia-back/` project structure with all directories
- Define the `Document` SQLAlchemy model (`id`, `content`, `embedding`, `tsvector`, `metadata`)
- Write and manage Alembic migrations (`CREATE EXTENSION vector`, table DDL, ivfflat + GIN indexes)
- Implement the DB connection factory that reads `THERMIA_ENV` and branches between `sshtunnel` and direct SQLAlchemy engine
- Provide unit tests for the connection factory (both branches, mocked)

## Public Interfaces
| Interface | Consumer | Description |
|---|---|---|
| `thermia-back/app/db/connection.py::get_engine()` | `ingestion-pipeline`, `retrieval-api` | Returns a SQLAlchemy `Engine`; activates SSH tunnel when `THERMIA_ENV=local` |
| `thermia-back/app/db/models.py::Document` | `ingestion-pipeline`, `retrieval-api` | SQLAlchemy ORM model for the `documents` table |
| `thermia-back/alembic/` | CI / manual setup | Alembic env + migration scripts |

## Internal Dependencies
None (Layer 0 — first unit built).

## External Dependencies
| Package | Version (pinned) | Purpose |
|---|---|---|
| `fastapi` | latest stable | App framework scaffold |
| `sqlalchemy` | `>=2.0` | ORM + Core |
| `alembic` | latest stable | DB migrations |
| `pgvector` | latest stable | `Vector(1024)` column type |
| `psycopg2-binary` | latest stable | PostgreSQL driver |
| `sshtunnel` | latest stable | SSH tunnel for local dev |
| `python-dotenv` | latest stable | `.env` loading |

## Tasks
| Task | Description |
|---|---|
| DB-T1 | Create `thermia-back/` skeleton (directories, `requirements.txt`, FastAPI stub) |
| DB-T2 | Write `Document` model with `Vector(1024)` embedding column |
| DB-T3 | Initialize Alembic; write initial migration with `CREATE EXTENSION vector`, table + indexes |
| DB-T4 | Write DB connection factory (`THERMIA_ENV` branching; SSH tunnel or direct engine) |
| DB-T5 | Unit tests: connection factory (both paths, mocked) |

## Acceptance Criteria (rolled up)
- [ ] `thermia-back/` exists with `app/`, `scripts/`, `tests/`, `alembic/` directories; `requirements.txt` present
- [ ] `uvicorn app.main:app` starts without import errors
- [ ] `Document` model has all 5 columns; `embedding` is `Vector(1024)`
- [ ] `alembic upgrade head` applies cleanly on a fresh DB with pgvector extension
- [ ] `alembic downgrade base` reverts cleanly
- [ ] `get_engine()` with `THERMIA_ENV=local` creates an SSH tunnel using the 4 SSH env vars
- [ ] `get_engine()` with `THERMIA_ENV=production` returns a plain SQLAlchemy engine from `DATABASE_URL`
- [ ] `pytest tests/test_db.py` passes with mocked tunnel + engine

## Definition of Done
- All tasks complete with green tests
- `alembic upgrade head` verified against a real Postgres instance (or mock)
- No hardcoded connection strings in any source file
- `requirements.txt` pinned and committed
