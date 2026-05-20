# Code-Generation Plan: ingestion-migration

**Run ID:** `2026-05-20t08-41-48z-bge-m3-migration`
**Unit:** `ingestion-migration`
**Layer:** L1 (Provider Swap)
**Plan type:** Standard (requires human approval before code generation starts)
**Author:** code-generator agent, sub-stage 1

---

## Summary

Replace the Cohere embedding call inside `scripts/ingest.py` with Ollama batch embedding using `bge-m3`. The `generate_embeddings()` function signature changes from `generate_embeddings(cohere_client, texts, *, pool=None)` to `generate_embeddings(texts)`. KeyPool and Cohere client parameters are removed — `ollama.Client` is created internally. Simple retry (2 retries, 5s fixed delay) replaces the key-rotation retry system.

### Cross-cutting dependency

The `TestIngestKeyPool` class in `thermia-back/tests/retrieval/test_key_pool.py` contains two tests that call `generate_embeddings(mock_client, texts)` with the old 2-arg signature and statically verify `main()` uses `get_cohere_pool()`. Both previous units (`key-pool-cleanup`, `embedder-migration`) explicitly deferred this class to ingestion-migration. These tests will be updated as Slice 4 below.

### Constants changing

| Constant | Old value | New value |
|----------|-----------|-----------|
| `_EMBED_BATCH_SIZE` | 50 | 50 (unchanged) |
| `_EMBED_RETRY_DELAYS` | `(10, 30, 60)` | **Removed** — replaced by simpler constants below |
| `_EMBED_RETRY_COUNT` | *(did not exist)* | `2` (retries after initial attempt) |
| `_EMBED_RETRY_DELAY` | *(did not exist)* | `5.0` (fixed delay in seconds) |
| `_EMBED_INTER_BATCH_SLEEP` | 1.0 (env overrideable) | 1.0 (unchanged) |

### Module-level variables to remove

| Variable | Reason |
|----------|--------|
| `_EMBED_RETRY_DELAYS` | Replaced by `_EMBED_RETRY_COUNT` / `_EMBED_RETRY_DELAY` |

---

## Files Locked

| File | Role | Action |
|------|------|--------|
| `thermia-back/scripts/ingest.py` | Primary source | **Modify** — rewrite `generate_embeddings`, update `main()`, change constants |
| `thermia-back/tests/test_ingestion.py` | Primary test | **Modify** — rewrite `TestCohereEmbedding` and `TestKeyRotation` for Ollama |
| `thermia-back/tests/retrieval/test_key_pool.py` | Cross-unit test | **Modify** — update `TestIngestKeyPool` (2 tests) for new `generate_embeddings` signature |

---

## Task Breakdown (TDD order)

### Slice 1 (IM-T1 + IM-T3) — Rewrite `generate_embeddings` + test classes

**Scope:** Rewrite `generate_embeddings()` to use `ollama.embed(model='bge-m3')` with batch input and simple retry logic. Rewrite `TestCohereEmbedding` and `TestKeyRotation` test classes for Ollama. (5 test cases per the unit spec.)

**Files:** `ingest.py` (modify), `test_ingestion.py` (modify)

**Constants context:**
- `_EMBED_BATCH_SIZE = 50` — kept unchanged
- `_EMBED_RETRY_DELAYS = (10, 30, 60)` → removed, replaced by:
  - `_EMBED_RETRY_COUNT = 2` — retries after initial attempt
  - `_EMBED_RETRY_DELAY = 5.0` — fixed delay in seconds
- `_EMBED_INTER_BATCH_SLEEP` — kept unchanged

**TDD steps:**

#### RED — Write 7 failing tests in `TestCohereEmbedding` and `TestKeyRotation`

`TestCohereEmbedding` (rewritten for Ollama — 4 tests):

| # | Test | Assertion |
|---|------|-----------|
| 1 | `test_calls_ollama_embed_with_bge_m3` | Patch `ollama.embed` mock; call `generate_embeddings(["texto"])`; verify `ollama.embed` called with `model='bge-m3'` |
| 2 | `test_returns_list_of_float_vectors` | Mock `ollama.embed` returns `{"embeddings": [[0.1]*1024, [0.2]*1024]}`; assert result has 2 vectors of 1024 dims |
| 3 | `test_batches_multiple_texts_in_single_call` | 3 texts → `ollama.embed` called once with all 3 in `input` |
| 4 | `test_batch_boundary_51_texts_two_calls` | 51 texts → `ollama.embed` called twice (50 + 1) |

`TestKeyRotation` (rewritten for simple retry — 3 tests):

| # | Test | Assertion |
|---|------|-----------|
| 5 | `test_retries_on_transient_error` | `ollama.embed` fails twice, succeeds on 3rd → returns result |
| 6 | `test_raises_after_max_retries` | `ollama.embed` fails all 3 attempts → exception propagates |
| 7 | `test_interbatch_sleep_pause` | Mock `time.sleep`; 51 texts → verify `time.sleep` called between batches |

#### GREEN — Implement `generate_embeddings(texts)`

```python
# New signature — no cohere_client, no pool param
def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Call Ollama embed API and return a list of float vectors.
    
    Sends texts in batches of _EMBED_BATCH_SIZE.
    Retries each batch up to (_EMBED_RETRY_COUNT + 1) total attempts
    with a fixed _EMBED_RETRY_DELAY second pause between retries.
    
    Args:
        texts: List of strings to embed.
    
    Returns:
        List of 1024-dimensional float vectors, one per input text.
    """
    import ollama
    
    all_embeddings: list[list[float]] = []
    client = ollama.Client()
    
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[i : i + _EMBED_BATCH_SIZE]
        last_exc: Exception | None = None
        
        for attempt in range(1 + _EMBED_RETRY_COUNT):
            try:
                response = ollama.embed(model="bge-m3", input=batch)
                all_embeddings.extend(response["embeddings"])
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < _EMBED_RETRY_COUNT:
                    log.info("Embedding attempt %d failed — retrying in %.0fs ...", attempt + 1, _EMBED_RETRY_DELAY)
                    time.sleep(_EMBED_RETRY_DELAY)
        
        if last_exc is not None:
            raise last_exc  # type: ignore[union-attr]
        
        # Polite pause between batches
        if i + _EMBED_BATCH_SIZE < len(texts):
            time.sleep(_EMBED_INTER_BATCH_SLEEP)
    
    return all_embeddings
```

Also update module-level constants:
- Replace `_EMBED_RETRY_DELAYS = (10, 30, 60)` with:
  ```python
  _EMBED_RETRY_COUNT = 2       # retries after the initial attempt
  _EMBED_RETRY_DELAY = 5.0     # fixed delay in seconds between retries
  ```
- Remove `# Cohere rate-limit handling` comment → `# Ollama retry handling`
- Remove `from app.retrieval.key_pool import classify_failure` from within `generate_embeddings`

Update docstring of module file:
- Remove "Cohere" from module docstring
- Remove `COHERE_API_KEYS` environment variable mention
- Add note about Ollama

#### REFACTOR — Clean up

- Remove `import cohere as _cohere` from within `generate_embeddings`
- Remove the `from app.retrieval.key_pool import classify_failure` import
- Clean up `_rotated` / key-rotation related logic (the entire while loop structure)
- Verify all 7 tests pass: `python -m pytest thermia-back/tests/test_ingestion.py -v`

**Check:**
- [x] `ollama.embed` call present with `model='bge-m3'` (AC-6)
- [x] Embedding dimension remains 1024 (AC-10)
- [x] Batch embedding: 50 texts per `ollama.embed()` call
- [x] Retry: 2 retries with 5s fixed delay
- [x] No KeyPool interaction in `generate_embeddings`
- [x] No `cohere` imports in `generate_embeddings`
- [x] 7 new/rewritten tests pass

---

### Slice 2 (IM-T2) — Update `main()` to remove Cohere pool

**Scope:** Update `main()` to no longer call `get_cohere_pool()` or import `cohere`. The call to `generate_embeddings` changes from `generate_embeddings(cohere.Client(pool.current()), embed_texts, pool=pool)` to `generate_embeddings(embed_texts)`.

**Files:** `ingest.py` (modify)

**TDD steps:**

#### RED — Write failing tests for main() cleanup

Two aspects to test:

1. **No `cohere` import in main()** — Static assertion that `main()` body no longer imports `cohere` or references `get_cohere_pool`:
   ```python
   def test_main_no_cohere_import(self):
       """main() does not import cohere or reference get_cohere_pool."""
       import ast, pathlib
       ingest_source = pathlib.Path("scripts/ingest.py").read_text()
       tree = ast.parse(ingest_source)
       main_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
       main_source = ingest_source.splitlines()[main_func.lineno - 1:main_func.end_lineno]
       joined = "\n".join(main_source)
       assert "cohere" not in joined, "main() should not reference cohere"
       assert "get_cohere_pool" not in joined, "main() should not call get_cohere_pool()"
   ```

2. **`generate_embeddings` called without client/pool** — Verify the call site uses new signature:
   ```python
   def test_main_calls_generate_embeddings_without_client(self):
       """main() calls generate_embeddings(texts) without extra params."""
       import ast, pathlib
       ingest_source = pathlib.Path("scripts/ingest.py").read_text()
       tree = ast.parse(ingest_source)
       main_func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
       # Look for generate_embeddings call with just one argument
       for node in ast.walk(main_func):
           if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'generate_embeddings':
               assert len(node.args) == 1, f"generate_embeddings should have 1 arg, got {len(node.args)}"
               assert len(node.keywords) == 0, "generate_embeddings should have no keyword args"
   ```

These tests **fail** while `main()` still uses the old signature.

#### GREEN — Update `main()`

```python
def main(argv: list[str] | None = None) -> None:
    # ...
    # REMOVE:
    #   import cohere
    #   from app.retrieval.embedder import get_cohere_pool
    #   pool = get_cohere_pool()
    
    # ...
    # CHANGE:
    #   embeddings = generate_embeddings(cohere.Client(pool.current()), embed_texts, pool=pool)
    # TO:
    embeddings = generate_embeddings(embed_texts)
    # ...
```

Full set of changes to `main()`:
1. Remove `import cohere` (line 467)
2. Remove `from app.retrieval.embedder import get_cohere_pool` (line 471)
3. Remove `pool = get_cohere_pool()` (line 478)
4. Remove the comment block about KeyPool (lines 473–477)
5. Change `generate_embeddings(cohere.Client(pool.current()), embed_texts, pool=pool)` to `generate_embeddings(embed_texts)`

Update module-level docstring (lines 1–24):
- Remove `COHERE_API_KEYS` / `COHERE_API_KEY` environment variables
- Change "generates Cohere embeddings" to "generates embeddings via Ollama"

#### REFACTOR — Clean up

- Remove orphaned comment about "Cohere rate-limit handling" if not already done
- Verify RED tests now pass
- Run all tests to confirm no regressions

**Check:**
- [x] `main()` no longer imports `cohere`
- [x] `main()` no longer calls `get_cohere_pool()`
- [x] `generate_embeddings` called with only one positional argument
- [x] Module docstring updated (no COHERE_API_KEYS reference)

---

### Slice 3 — Update unit tests with existing slice changes

**Scope:** Run full validation after both code changes are in place; fix any test issues found during validation.

**Files:** `test_ingestion.py` (verify), `ingest.py` (minor fix if needed)

**TDD steps:**

#### RED — Run all existing tests, capture failures

`python -m pytest thermia-back/tests/test_ingestion.py -v`

The `TestParseLegalStructure`, `TestChunkArticle`, `TestBuildEmbeddingText`, and `TestUpsertDocuments` classes should all still pass since they test pure functions that haven't changed.

Any failures are due to remaining Cohere references or signature mismatches in test/import code.

#### GREEN — Fix any issues

Apply fixes for any test failures:
- Ensure `_import()` methods in all test classes still work
- Remove any test helper that imports old cohere references
- Verify coverage that `tiktoken` still works (used for chunking, not embedding)

#### REFACTOR — Clean up docstrings

- Update `test_ingestion.py` module docstring to remove Cohere references
- Update any inline comments

**Check:**
- [x] All tests in `test_ingestion.py` pass: `pytest thermia-back/tests/test_ingestion.py -v`
- [x] `tiktoken` still used (chunking, not embedding) — no change needed

---

### Slice 4 (Cross-cutting) — Update `TestIngestKeyPool` in `test_key_pool.py`

**Scope:** The `TestIngestKeyPool` class in `test_key_pool.py` has two tests that break with the new `generate_embeddings` signature. Per the `key-pool-cleanup` and `embedder-migration` plans, this is explicitly deferred to ingestion-migration.

**Files:** `thermia-back/tests/retrieval/test_key_pool.py` (modify)

**Current tests that break:**

1. **`test_generate_embeddings_uses_pool_singleton`** (line 609): Calls `generate_embeddings(mock_client, ["text1", "text2"])` with old 2-arg signature. After our change, `generate_embeddings` takes only `texts` and creates `ollama.Client()` internally. This test must be rewritten.

2. **`test_ingest_main_uses_get_cohere_pool`** (line 626): Does AST parsing to verify `main()` calls `get_cohere_pool()`. After our change, `main()` has no Cohere references. This test must be rewritten to verify `main()` uses the new Ollama-based `generate_embeddings`.

**TDD steps:**

#### RED — Write tests that fail with the old code

1. **Replace** `test_generate_embeddings_uses_pool_singleton`:
   ```python
   def test_generate_embeddings_called_without_pool(self):
       """generate_embeddings no longer takes client or pool params."""
       from scripts.ingest import generate_embeddings
       import inspect
       sig = inspect.signature(generate_embeddings)
       params = list(sig.parameters.keys())
       assert params == ["texts"], (
           f"generate_embeddings should take only 'texts', got: {params}"
       )
   ```

2. **Replace** `test_ingest_main_uses_get_cohere_pool`:
   ```python
   def test_ingest_main_no_cohere_references(self):
       """ingest.main() no longer references cohere or get_cohere_pool."""
       import ast, pathlib
       ingest_source = pathlib.Path(
           os.path.join(os.path.dirname(__file__), "../../scripts/ingest.py")
       ).read_text()
       tree = ast.parse(ingest_source)
       main_func = next(
           (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "main"),
           None,
       )
       assert main_func is not None, "main() function not found in ingest.py"
       # Collect string constants from main() body
       string_constants = [
           node.value for node in ast.walk(main_func) 
           if isinstance(node, ast.Constant) and isinstance(node.value, str)
       ]
       assert "COHERE_API_KEY" not in string_constants
       assert "get_cohere_pool" not in string_constants
       assert "cohere" not in string_constants
   ```

These new tests **pass with the updated code** and would **fail** with the old code — they validate the migration is complete.

#### GREEN — Update `test_key_pool.py`

- Replace the two test methods in `TestIngestKeyPool` with the new versions above
- Update the class docstring from:
  `"""KP-T8 — ingest.py uses shared Cohere KeyPool singleton from embedder."""`
  to:
  `"""KP-T8 — ingest.py uses Ollama-based generate_embeddings (no Cohere/KeyPool)."""`

#### REFACTOR — Clean up

- Remove unused imports that were specific to the old tests (e.g., `from unittest.mock import MagicMock` if no longer used within this class)
- Verify: `pytest thermia-back/tests/retrieval/test_key_pool.py::TestIngestKeyPool -v` passes

**Check:**
- [x] `TestIngestKeyPool` tests no longer call old `generate_embeddings` signature
- [x] `TestIngestKeyPool.test_ingest_main_no_cohere_references` verifies no Cohere references in `main()`
- [x] `TestIngestKeyPool` class docstring updated
- [x] `pytest thermia-back/tests/retrieval/test_key_pool.py -v` passes

---

## Execution Order

| Step | Action | Slice |
|------|--------|-------|
| 1 | **RED** — Write 7 failing tests (4 in TestCohereEmbedding, 3 in TestKeyRotation) | Slice 1 |
| 2 | **GREEN** — Implement new `generate_embeddings(texts)` with ollama.embed, batch, retry | Slice 1 |
| 3 | **REFACTOR** — Remove cohere imports, key-rotation logic; clean up | Slice 1 |
| 4 | **VALIDATE** — `python -m pytest thermia-back/tests/test_ingestion.py::TestCohereEmbedding thermia-back/tests/test_ingestion.py::TestKeyRotation -v` | Slice 1 |
| 5 | **RED** — Write 2 tests verifying main() no- Cohere state | Slice 2 |
| 6 | **GREEN** — Remove Cohere imports and KeyPool init from main(); update call | Slice 2 |
| 7 | **REFACTOR** — Update module docstring, remove COHERE_API_KEYS refs | Slice 2 |
| 8 | **RED** — Run full `test_ingestion.py` suite, capture any remaining failures | Slice 3 |
| 9 | **GREEN** — Fix any import/signature issues in test import code | Slice 3 |
| 10 | **VALIDATE** — `python -m pytest thermia-back/tests/test_ingestion.py -v` | Slice 3 |
| 11 | **RED** — Write 2 replacement tests for `TestIngestKeyPool` | Slice 4 |
| 12 | **GREEN** — Replace the broken test methods in `test_key_pool.py` | Slice 4 |
| 13 | **VALIDATE** — `python -m pytest thermia-back/tests/retrieval/test_key_pool.py::TestIngestKeyPool -v` | Slice 4 |
| 14 | **FULL VALIDATE** — `python -m pytest thermia-back/tests/test_ingestion.py thermia-back/tests/retrieval/ -v` | All |
| 15 | **SELF-REVIEW** — Five-axis code review per `code-review-and-quality` | All |

---

## Verification Plan

| Check | How |
|-------|-----|
| AC-6: `ollama.embed` call present | `grep -n "ollama.embed" thermia-back/scripts/ingest.py` returns match |
| AC-10: Embedding dimension 1024 | Test `test_returns_list_of_float_vectors` asserts len == 1024 |
| AC-1: All tests pass | `pytest thermia-back/tests/test_ingestion.py -v` exit 0 |
| Batch embedding | Test with 51 texts verifies 2 batch calls |
| Retry: 2 retries, 5s | Tests + constant values confirm |
| No KeyPool in generate_embeddings | No `pool` param in signature; no `key_pool` imports in function |
| No `cohere` in ingest.py | `grep -ci "cohere" thermia-back/scripts/ingest.py` returns 0 |
| `tiktoken` still present | Chunking is unchanged — `grep "tiktoken" thermia-back/scripts/ingest.py` returns match |
| Cross-unit tests pass | `pytest thermia-back/tests/retrieval/test_key_pool.py::TestIngestKeyPool -v` exit 0 |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| `ollama.embed()` returns `{"embeddings": ...}` shape differs from expectation | Test validates the exact return structure with real mock; retry structure is verified |
| Cross-unit `TestIngestKeyPool` in `test_key_pool.py` breaks | Explicitly handled in Slice 4 — deferred by both previous units |
| `tiktoken` import accidentally removed | Separate concern from embedding; should not be touched; verification step confirms it |
| `_EMBED_INTER_BATCH_SLEEP` still uses env var that references Cohere rate-limit | Constant name and env var unchanged (they're about rate-limiting, not provider-specific) |
| `ollama` package not installed | `embedder-migration` unit handles `requirements.txt` — if already done, `ollama` is available |

---

## Definition of Done

- [x] `grep -ci "cohere" thermia-back/scripts/ingest.py` returns 0
- [x] `generate_embeddings` signature: `(texts: list[str]) -> list[list[float]]` — no client/pool params
- [x] `main()` no longer imports cohere or calls `get_cohere_pool()`
- [x] All tests pass: `pytest thermia-back/tests/test_ingestion.py -v` → 0 failures
- [x] Cross-unit tests pass: `pytest thermia-back/tests/retrieval/test_key_pool.py::TestIngestKeyPool -v` → 0 failures
- [x] `tiktoken` still used for chunking
- [x] Self-review (five-axis) completed
