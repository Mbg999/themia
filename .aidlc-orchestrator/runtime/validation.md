# Lightweight Validation (inline stages)

PRIORITY: P3

Inline stages do NOT run full JSON Schema validation. They MUST still verify:
- required fields are present
- status enums are valid
- referenced artifacts exist
- predecessor references resolve correctly
- critical outputs are non-null

On validation failure: emit `fail-stage` → append validation failure to audit →
halt stage → surface to user.

See `index.md §1` for the validation mode matrix.
