# Build Instructions — ingestion-migration

Run ID: `2026-05-20t08-41-48z-bge-m3-migration`
Unit: `ingestion-migration`
Date: 2026-05-20

## Environment

| Component | Version |
|-----------|---------|
| Python | 3.11.9 (homebrew) |
| pytest | >= 8.0.0 |
| pgvector | 0.4.2 |
| tiktoken | >= 0.7.0 |
| ollama | >= 0.6.2 |

## Prerequisites

```bash
# Verify Python 3.11 is available
python3.11 --version

# Install required package if missing
pip3.11 install pgvector --break-system-packages
```

Note: `pgvector` must be installed for `app.db.models` to import. Without it,
`TestUpsertDocuments` tests fail with `ModuleNotFoundError: No module named 'pgvector'`.

## Running the Test Suite

All commands run from `/Users/miguel.belmonte/Desktop/thermia/thermia-back`.

### Primary test target

```bash
cd /Users/miguel.belmonte/Desktop/thermia/thermia-back
python -m pytest tests/test_ingestion.py -v
```

Expected: 46 passed, 0 failed.

### Cross-unit test target

```bash
python -m pytest tests/retrieval/test_key_pool.py::TestIngestKeyPool -v
```

Expected: 2 passed, 0 failed.

### Full combined run

```bash
python -m pytest tests/test_ingestion.py tests/retrieval/ -v
```

Expected: 108 passed, 2 failed (pre-existing known failures in TestLLMKeyPool).

### Static acceptance checks

```bash
# AC: no cohere references in ingest.py (should print 0)
grep -ci "cohere" scripts/ingest.py

# AC-6: ollama.embed present with bge-m3
grep -n "ollama.embed" scripts/ingest.py

# AC: tiktoken used for chunking
grep "tiktoken" scripts/ingest.py
```

## Known Pre-existing Failures (Out of Scope)

The following two tests in `tests/retrieval/test_key_pool.py` fail due to a
`model_validate_json` mock issue in `llm.py` that predates the bge-m3 migration:

- `TestLLMKeyPool::test_llm_uses_active_groq_key`
- `TestLLMKeyPool::test_groq_daily_quota_rotates_and_retries`

These are NOT regressions from this unit. Do NOT modify `llm.py` or those tests.
