# Unit Spec: `metadata-helpers`
**Run:** `2026-05-19t20-50-00z-metadata-refactor`
**Layer:** 0 (no dependencies — builds independently)

## Purpose
A pure-function library module (`app/ingestion/metadata_helpers.py`) that extracts, normalizes, and hashes legal document metadata from YAML frontmatter. All functions are side-effect-free (no I/O, no DB, no Cohere) and fully testable in isolation.

## Responsibilities
- Parse YAML frontmatter from Markdown files safely (`parse_frontmatter`)
- Compute stable SHA256 content hashes for embedding-skip decisions (`compute_content_hash`)
- Extract and normalize Spanish legal rank from frontmatter or title (`extract_legal_rank`)
- Normalize legal status to Spanish domain values (`normalize_status`)
- Derive ELI identifier conservatively from frontmatter fields (`derive_eli`)
- Full unit test coverage for all 5 functions (≥25 tests, no external deps)

## Public Interfaces (consumed by other units)
All functions exported from `app.ingestion.metadata_helpers`:

```python
def parse_frontmatter(md_text: str) -> tuple[dict, str]: ...
def compute_content_hash(text: str) -> str: ...
def extract_legal_rank(frontmatter: dict, law_title: str) -> str: ...
def normalize_status(raw: str | None) -> str: ...
def derive_eli(frontmatter: dict) -> str | None: ...
```

**Consumed by:** `ingestion-wiring` unit (imports all 5 functions).

## Internal Dependencies
None — this unit has no dependency on other units in this run.

## External Dependencies
- `PyYAML>=6.0` — for `yaml.safe_load` in `parse_frontmatter`
- `hashlib` — stdlib, for SHA256 in `compute_content_hash`
- `re` — stdlib, for whitespace normalization and pattern matching
- `logging` — stdlib, for WARNING on unknown status values

## Tasks
| Task | Description |
|---|---|
| MH-T1 | Create `app/ingestion/__init__.py` + `metadata_helpers.py` skeleton |
| MH-T2 | Implement `parse_frontmatter` — detect/strip `---` block, `yaml.safe_load`, safe error handling |
| MH-T3 | Implement `compute_content_hash` — normalize whitespace + SHA256 |
| MH-T4 | Implement `extract_legal_rank` — frontmatter rank priority, then title pattern matching |
| MH-T5 | Implement `normalize_status` — EN→ES mapping with WARNING on unknown |
| MH-T6 | Implement `derive_eli` — direct field, then URL extraction; never raises |
| MH-T7 | Write `tests/ingestion/test_metadata_helpers.py` — ≥25 tests across 5 classes |

## Acceptance Criteria
- `from app.ingestion.metadata_helpers import parse_frontmatter` succeeds (no DB/Cohere import)
- `parse_frontmatter("---\ntitle: X\n---\n# H1")` → `({"title": "X"}, "\n# H1")`
- `parse_frontmatter("---\n: broken\n---\n# H1")` → `({}, original)` + WARNING logged
- `compute_content_hash("  Hello  World  ")` == `compute_content_hash("hello world")`
- `normalize_status("in_force")` == `"vigente"`; `normalize_status(None)` == `""`
- `extract_legal_rank({"rank": "real-decreto"}, "")` == `"real_decreto"`
- `extract_legal_rank({}, "Ley Orgánica 3/2007")` == `"ley_organica"`
- `derive_eli({"source": "https://boe.es/eli/es/rd/2023/001"})` → `"eli/es/rd/2023/001"`
- `derive_eli({})` → `None` (not `""`)
- `pytest tests/ingestion/test_metadata_helpers.py -v` → all ≥25 tests pass

## Definition of Done
- [ ] `app/ingestion/__init__.py` created
- [ ] `app/ingestion/metadata_helpers.py` with all 5 functions implemented
- [ ] `tests/ingestion/__init__.py` created
- [ ] `tests/ingestion/test_metadata_helpers.py` with ≥25 tests (all passing)
- [ ] `PyYAML>=6.0` in `requirements.txt` (if not already present)
- [ ] No regressions in existing test suite
