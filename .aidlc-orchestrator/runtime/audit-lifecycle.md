# Audit Log Lifecycle

PRIORITY: P4

`aidlc-docs/audit.md` is the append-only event log. Follow **tail + archive**
policy to prevent unbounded growth.

> **Orchestrator override:** When using `/factory-*` commands, the orchestrator
> manages `audit.md` automatically. Skip this section.

## Structure
```
# Audit Log

## Summary
- Current Phase: <phase>
- Stages Completed: <summary>
- Entry Count: <N> current (+ <M> archived)
- Archives: aidlc-docs/archive/audit-<phase>.md

## Entries
<last N entries in chronological order>
```

## Entry definition
Starts with `## <ISO8601> ...` heading. Everything between it and next `##` is one entry.

## Archive trigger
Archive when either:
1. **Entry count > 30** — after appending a new entry
2. **Phase transition** — entering new phase (Inception→Construction, Construction→Operations)

## Archive procedure
1. Create `aidlc-docs/archive/` if missing.
2. Move oldest completed-phase entries to `aidlc-docs/archive/audit-<phase>.md`.
3. Remove those entries from `audit.md`.
4. Update Summary header.
5. Archive files preserve original format and ISO 8601 timestamps.

## Usage
- **Session continuity**: Read `aidlc-state.md` first; load archives if full timeline needed.
- **Phase transition**: Read archives to verify prior phase completeness.
- **Archives are read-only** — new entries always go in `audit.md`.
