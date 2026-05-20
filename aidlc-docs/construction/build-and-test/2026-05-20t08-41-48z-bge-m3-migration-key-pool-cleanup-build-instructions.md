# Build Instructions — key-pool-cleanup

## Run ID
`2026-05-20t08-41-48z-bge-m3-migration`

## Unit
`key-pool-cleanup`

## Environment
- **OS**: macOS (Darwin)
- **Python**: 3.9.6 (system) / 3.11.9 (brew — used by pytest)
- **pytest**: 9.0.3
- **pip**: 26.0.1
- **Shell**: zsh
- **CI**: No

## Reproducible Command Sequence

### 1. Environment detection
```bash
# Platform fingerprint
uname -s                    # Darwin
command -v python3 && python3 --version
command -v pytest && pytest --version
command -v pip3 && pip3 --version
```

### 2. Run tests
```bash
cd /Users/miguel.belmonte/Desktop/thermia
pytest thermia-back/tests/retrieval/test_key_pool.py -v
```

### 3. Verify Cohere cleanup in source
```bash
grep -ci "cohere" thermia-back/app/retrieval/key_pool.py
# Expected: 0 (exit code 1)

grep -ci "cohere" thermia-back/tests/retrieval/test_key_pool.py
# Expected: 38 (all in TestEmbedderKeyPool, TestIngestKeyPool, and red-test helpers)
```

### 4. Verify no cohere in LLM tests
```bash
grep -c "cohere" thermia-back/tests/retrieval/test_key_pool.py | grep -v "TestEmbedder\|TestIngest\|test_no_cohere"
# Expected: 0 — TestLLMKeyPool tests use "groq" only
```

## Dependencies
No new dependencies were introduced. Tests use `pytest`, `unittest.mock`, `pytest.monkeypatch`.

## Validation
No static validators (pyright/mypy) are configured for this project. Validation relies on test execution only.

## Output Artifacts
- `aidlc-docs/construction/build-and-test/<run-id>-build-and-test-summary.md`
- `.aidlc-orchestrator/runs/<run-id>/handoffs/build-test.key-pool-cleanup.output.yaml`
