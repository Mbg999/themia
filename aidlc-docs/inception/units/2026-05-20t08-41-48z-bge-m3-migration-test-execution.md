# Unit Spec: test-execution

**Run ID:** `2026-05-20t08-41-48z-bge-m3-migration`
**Layer:** L2 (Verification)

## Purpose

Run the full test suite and perform manual endpoint verification to confirm the migration is complete and all acceptance criteria are met.

## Responsibilities

- Execute `pytest thermia-back/tests/ -v` — verify all tests pass
- Manual POST /analyze smoke test — verify valid response
- Grep-verify no Cohere references remain in source files
- Document rollback procedure

## Public Interfaces

None (verification only).

## Internal Dependencies

- `embedder-migration` — embedder and deps must be migrated
- `ingestion-migration` — ingest must be migrated

## External Dependencies

- pytest
- Ollama service (for manual endpoint test)

## Tasks (from execution plan)

| Task | Description | ACs |
|------|-------------|-----|
| TE-T1 | Run `pytest thermia-back/tests/ -v` | AC-1 |
| TE-T2 | Manual smoke: POST /analyze returns valid response | AC-2 |
| TE-T3 | Grep-verify: no cohere refs in embedder.py, key_pool.py, ingest.py | AC-3, AC-4 |

## Acceptance Criteria

- AC-1: All unit tests pass
- AC-2: POST /analyze returns valid 200 response
- AC-3: No cohere import in embedder.py
- AC-4: No cohere reference in key_pool.py
- AC-8: Rollback procedure documented (git revert + Cohere env vars retained)

## Definition of Done

- [ ] `pytest thermia-back/tests/ -v` — exit 0, all tests pass
- [ ] Manual `POST /analyze` returns valid JSON with expected fields
- [ ] No cohere refs in any migrated source file
- [ ] Rollback documented in migration notes
