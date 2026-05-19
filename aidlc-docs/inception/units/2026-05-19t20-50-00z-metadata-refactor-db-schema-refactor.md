# Unit Spec: `db-schema-refactor`
**Run:** `2026-05-19t20-50-00z-metadata-refactor`
**Layer:** 0 (no dependencies — builds independently)

## Purpose
Extend the `documents` table schema to support two-layer metadata storage, legal filtering columns, and efficient JSONB querying. This is the data-contract unit — all other units that write to the DB depend on these columns existing.

## Responsibilities
- Add 4 new columns to `documents`: `status VARCHAR(32)`, `legal_rank VARCHAR(64)`, `jurisdiction VARCHAR(8)`, `source_metadata JSONB`
- Add 4 new indexes: B-tree on `status`, `legal_rank`, `jurisdiction`; GIN on `metadata jsonb_path_ops`
- Update the SQLAlchemy `Document` ORM model to reflect all new columns
- Provide upgrade + downgrade migration (Alembic `0003_metadata_refactor.py`)

## Public Interfaces (consumed by other units)
- **`Document` ORM class** (`app/db/models.py`) — exposes new attributes:
  - `doc.status: str`
  - `doc.legal_rank: str`
  - `doc.jurisdiction: str`
  - `doc.source_metadata_: dict` (mapped to column `source_metadata`)
- **Alembic migration `0003`** — applies schema changes; `ingestion-wiring` assumes these columns exist before upsert

## Internal Dependencies
None — this unit has no dependency on other units in this run.

## External Dependencies
- SQLAlchemy `>=2.0.0` (already in `requirements.txt`)
- Alembic `>=1.14.0` (already in `requirements.txt`)
- PostgreSQL with pgvector extension (running via Docker Compose)

## Tasks
| Task | Description |
|---|---|
| DB-T1 | Add 4 new columns to `Document` SQLAlchemy model |
| DB-T2 | Write `0003_metadata_refactor.py` Alembic migration (upgrade + downgrade) |
| DB-T3 | Extend `tests/test_db.py` — model column assertions + offline SQL verification |

## Acceptance Criteria
- `Document` model imports without error; all 4 new attributes accessible
- `Document.__table__.c['status'].type` is `String(32)`
- `Document.__table__.c['legal_rank'].type` is `String(64)`
- `Document.__table__.c['jurisdiction'].type` is `String(8)`
- `Document.__table__.c['source_metadata'].type.__class__.__name__ == 'JSONB'`
- `alembic upgrade head --sql` produces DDL with 4 `ADD COLUMN` + 4 `CREATE INDEX` statements
- `alembic downgrade base --sql` drops all 4 columns and 4 indexes cleanly
- `pytest tests/test_db.py -v` — all tests pass, no DB connection required

## Definition of Done
- [ ] `app/db/models.py` updated with 4 new columns
- [ ] `alembic/versions/0003_metadata_refactor.py` created and validated offline
- [ ] `tests/test_db.py` extended with 5 new test cases (all passing)
- [ ] No regressions in existing test suite
