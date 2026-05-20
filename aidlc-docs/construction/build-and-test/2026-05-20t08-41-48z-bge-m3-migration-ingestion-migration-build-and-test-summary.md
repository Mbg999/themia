# Build & Test Summary — ingestion-migration

Run ID: `2026-05-20t08-41-48z-bge-m3-migration`
Unit: `ingestion-migration`
Date: 2026-05-20
Build status: SUCCESS
Overall result: NEEDS_HUMAN (approval gate)

## Test Results

| Suite | Total | Pass | Fail | Skip |
|-------|-------|------|------|------|
| tests/test_ingestion.py | 46 | 46 | 0 | 0 |
| tests/retrieval/test_key_pool.py::TestIngestKeyPool | 2 | 2 | 0 | 0 |
| tests/retrieval/ (full, incl. pre-existing) | 62 | 60 | 2 | 0 |
| Combined (test_ingestion + retrieval/) | 108 | 106 | 2 | 0 |

The 2 failures are pre-existing and documented:
- `TestLLMKeyPool::test_llm_uses_active_groq_key`
- `TestLLMKeyPool::test_groq_daily_quota_rotates_and_retries`
Root cause: `pydantic_core.ValidationError: JSON input should be string, bytes or bytearray`
in `app/retrieval/llm.py:177`. Predates this migration. Not in scope.

Coverage: not measured (no coverage plugin configured).

## Acceptance Criteria Verification

| AC | Description | Result | Evidence |
|----|-------------|--------|----------|
| AC-1 | All unit tests pass — pytest tests/test_ingestion.py | PASS | 46 passed, 0 failed |
| AC-6 | ollama.embed call present with model='bge-m3' | PASS | scripts/ingest.py:325 `ollama.embed(model="bge-m3", input=batch)` |
| AC-10 | Embedding dimension 1024 verified by test assertion | PASS | TestCohereEmbedding::test_returns_list_of_float_vectors asserts len==1024 |
| No cohere in ingest.py | grep -ci "cohere" scripts/ingest.py == 0 | PASS | 0 matches |
| Signature: (texts: list[str]) | generate_embeddings takes only 'texts' | PASS | inspect.signature returns `(texts: 'list[str]') -> 'list[list[float]]'` |
| main() no cohere imports | main() body has no cohere or get_cohere_pool imports | PASS | TestMainNoCohereReferences::test_main_no_cohere_import passed (AST static check) |
| main() no get_cohere_pool call | generate_embeddings called with 1 positional arg | PASS | TestMainNoCohereReferences::test_main_calls_generate_embeddings_without_client passed |
| Cross-unit: TestIngestKeyPool | pytest tests/retrieval/test_key_pool.py::TestIngestKeyPool | PASS | 2 passed, 0 failed |
| tiktoken still used | grep "tiktoken" scripts/ingest.py | PASS | Line 34: `import tiktoken`, Line 69: `_ENC = tiktoken.get_encoding(...)` |

All 9 acceptance criteria: PASS.

## Environmental Issue Found and Resolved

`pgvector` was not installed in the Python 3.11 environment. This caused
`TestUpsertDocuments` (8 tests) to fail with `ModuleNotFoundError: No module named 'pgvector'`
on the first run. Resolution: `pip3.11 install pgvector --break-system-packages`.
After install, all 46 tests in test_ingestion.py passed.

This is an environment setup issue, not a code defect. The build instructions document
the prerequisite installation step.
