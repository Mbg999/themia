# Build Instructions — embedder-migration
## Run: 2026-05-20t08-41-48z-bge-m3-migration

### Environment

- Platform: Darwin 25.3.0 (macOS)
- Python: 3.14.5 (via homebrew at `/Users/miguel.belmonte/homebrew/opt/python@3.14/bin/python3.14`)
- Virtual environment: `thermia-back/.venv/`
- pytest: 9.0.3
- ollama (Python client): 0.6.2

### Prerequisites

1. Activate the virtual environment:
   ```bash
   source /Users/miguel.belmonte/Desktop/thermia/thermia-back/.venv/bin/activate
   ```

2. Verify ollama client is installed:
   ```bash
   python -m pip show ollama
   # Expected: Version: 0.6.2 or higher
   ```

3. Verify cohere is NOT in requirements.txt (it may still be installed in the venv
   from a prior pip install, but it must not appear in requirements.txt):
   ```bash
   grep "cohere" thermia-back/requirements.txt
   # Expected: no output
   ```

### Run Embedder Unit Tests Only

```bash
cd /Users/miguel.belmonte/Desktop/thermia/thermia-back
source .venv/bin/activate
python -m pytest tests/retrieval/test_embedder.py -v
```

Expected: 6 passed, 0 failed, 0 warnings (excluding pytest.ini-suppressed warnings).

### Run Full Retrieval Test Suite

```bash
cd /Users/miguel.belmonte/Desktop/thermia/thermia-back
source .venv/bin/activate
python -m pytest tests/retrieval/ -v --tb=short
```

Expected: 60 passed, 2 failed (known pre-existing failures — see below).

### Known Pre-Existing Failures (out-of-scope)

These two tests fail due to a `model_validate_json` mock issue in `llm.py` that
predates the embedder-migration. They are NOT in scope for this unit:

- `TestLLMKeyPool::test_llm_uses_active_groq_key`
- `TestLLMKeyPool::test_groq_daily_quota_rotates_and_retries`

Root cause: `llm.py:177` calls `AnalisisLegal.model_validate_json(json_string)` where
`json_string` is a `MagicMock` object (not a string/bytes), because the test's mock
does not patch the correct call path — `mock_response.model_dump.return_value` is set
but `llm.py` calls `model_validate_json` on `response.content`, not `.model_dump()`.

### Acceptance Criteria Verification

```bash
# AC-3: No cohere import in embedder.py
grep -c "cohere" app/retrieval/embedder.py
# Expected: 0 (command exits 1 — grep returns exit 1 when no matches)

# AC-5: ollama import present
grep -n "^import ollama" app/retrieval/embedder.py

# AC-7: OLLAMA_HOST env var configures endpoint
grep "OLLAMA_HOST" app/retrieval/embedder.py

# AC-9: ollama>=0.6.2 in requirements.txt
grep "ollama" requirements.txt
```

### Install Dependencies (if starting fresh)

```bash
cd /Users/miguel.belmonte/Desktop/thermia/thermia-back
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
