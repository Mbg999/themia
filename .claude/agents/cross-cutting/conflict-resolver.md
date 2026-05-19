---
name: conflict-resolver
description: AIDLC Orchestrator's parallel-safety layer. Owns the file-glob lock registry and Python AST symbol-drift detection. Detects conflicts when multiple parallel agents touch overlapping paths or change shared interfaces. NOT a Task() subagent — orchestrator invokes aidlc-scripts/factory_conflict.py directly.
---

# Conflict Resolver (Phase 5 — active)

> **Architectural note:** the Conflict Resolver is **not** a Task()-spawnable
> subagent. It is a *capability* the orchestrator exercises by calling
> `aidlc-scripts/factory_conflict.py` (CLI) and parsing its exit codes. This file
> is the canonical spec for HOW the orchestrator integrates conflict
> arbitration into parallel spawn cycles.

## Purpose

Prevent parallel agents from corrupting each other's work. Two failure modes
are detected:

1. **Path collision** — two write holders declare overlapping locks. The
   newer request is denied; a `path_collision` conflict record is written.
2. **Interface drift** — agent A modifies a public symbol that another
   in-flight agent B depends on. Detected by AST diff against a pre-spawn
   baseline. Triggers an `interface_drift` conflict record.

## Storage

```
.aidlc-orchestrator/runs/<run-id>/
├── locks/<holder>.yaml              # active locks per holder
├── symbol-baseline/<holder>.yaml    # AST snapshot, pre-spawn
└── conflicts/<id>.yaml              # path_collision | interface_drift records
```

Holders are stage instances. For `code-generator` running on unit
`auth-service`, the canonical holder name is `code-generator:auth-service`
(use the `<stage>:<unit>` form for per-unit stages; bare `<stage>` for
single-instance stages).

## Lock acquisition policy

| Requested | Existing | Outcome |
|---|---|---|
| `write` | (none) | granted |
| `write` | `write` (different holder, overlap) | **denied** — path_collision record |
| `write` | `read` (different holder, overlap) | **denied** — write blocks readers |
| `read`  | `read` (overlap) | granted (read-read sharing) |
| `read`  | `write` (overlap) | **denied** |
| any     | same holder | re-grant (file overwritten) |

**Glob overlap detection** is a heuristic: position-by-position component
match with `**` matching any depth. Biased toward false positives — over-
detecting overlap is safe; under-detecting would let conflicts slip through.

## When the orchestrator calls each subcommand

### Pre-spawn (acquire + snapshot)
```bash
# 1. Acquire write locks for the unit's declared paths
python3 aidlc-scripts/factory_conflict.py acquire <run-id> code-generator:<unit> \
    "src/<unit>/**" "tests/<unit>/**"
# Exit 0 → continue. Exit 1 → conflict record; halt this unit's spawn.

# 2. Snapshot AST baseline of all .py files the agent might modify
python3 aidlc-scripts/factory_conflict.py snapshot <run-id> code-generator:<unit> \
    src/<unit>/handler.py src/<unit>/jwt.py
```

### Post-spawn (check-symbols + release)
```bash
# 3. Diff modified files against the baseline
python3 aidlc-scripts/factory_conflict.py check-symbols <run-id> code-generator:<unit> \
    src/<unit>/handler.py src/<unit>/jwt.py
# Exit 0 → no drift, OR drift but no other active holders (logged but not a conflict).
# Exit 1 → drift AND other holders are active → interface_drift conflict written.

# 4. Release the unit's locks
python3 aidlc-scripts/factory_conflict.py release <run-id> code-generator:<unit>
```

## Resolution policies

Phase 5 ships **escalation only**. Auto-merge is documented in
`ORCHESTRATOR-PLAN.md §6.2` as a future feature but not implemented because
generic auto-merge is unsafe.

When a conflict record appears:
1. Orchestrator surfaces the record to the user with both diffs (or both
   declared-locks lists for path collisions).
2. User decides:
   - **Re-plan the loser** — orchestrator re-spawns the rejected unit with
     adjusted `locks_required` or different scope.
   - **Manual merge** — user resolves outside the orchestrator, then runs
     `/factory-build <run-id>` again to continue.
   - **Cancel the unit** — drop it from the layer; continue with the rest.
3. Update the conflict record's `resolution` and `resolved_by` fields.

The full priority/auto-merge ladder from `ORCHESTRATOR-PLAN.md §6.2` will
land in a future phase once we have data on which conflicts auto-merge
safely.

## Parallel `/factory-build` flow integration

For each layer of independent units (computed by topo-sort on `depends_on`):

```
1. Compute lock requirements per unit:
     locks_required = unit_spec.locks_required
                   or [f"src/{unit}/**", f"tests/{unit}/**"]   # default

2. Sequential pre-flight per unit (CHEAP — do all before any spawn):
     - factory_conflict.py acquire     (drop unit from layer if path_collision
                                        with another unit IN THIS LAYER)
     - factory_conflict.py snapshot    (Python files only)
     - mem_search                      (knowledge query)
     - build input handoff             (validate against schema)

3. Parallel spawn — single message with N Task() calls (N ≤ 4):
     Task(subagent_type="code-generator", prompt=".../<unit-1>.input.yaml")
     Task(subagent_type="code-generator", prompt=".../<unit-2>.input.yaml")
     ...

4. Sequential post-spawn per returned unit:
     - validate output handoff
      - factory_conflict.py check-symbols     (interface drift?)
     - knowledge save (mem_save per emitted_knowledge entry)
     - audit append
     - factory_conflict.py release           (always release, even on conflict)

5. If any conflict was raised in step 4, surface to user before next layer.
```

## Limitations (Phase 5 + 5.5)

- **Auto-merge not implemented.** All conflicts escalate to user.
- **Glob overlap is heuristic, not exhaustive.** Biased toward false
  positives (safe). Some edge cases (e.g. `src/{auth,user}/**` brace
  expansion) aren't handled — agents should declare separate globs instead.
- **AST diff covers Python (stdlib `ast`) and TS/JS (tree-sitter).**
  Phase 5.5 added `.ts/.tsx/.js/.jsx/.mts/.cts/.mjs/.cjs` support — extracts
  `export function/class/interface/type/enum` and `export const x = (...) => ...`.
  Re-exports (`export * from`, `export { x } from`), namespace exports, and
  ambient declarations are NOT tracked. Tree-sitter is an optional dep — if
  missing, TS/JS files snapshot as `tree_sitter_unavailable` and only path
  locking applies.
- **Deep TS type-system drift is out of scope.** Generics narrowing,
  conditional types, and inference chains aren't tracked at the signature
  level. That requires `tsc --noEmit` or LSP integration (Phase 7+).
- **No queueing.** When a lock is denied, the request fails outright. No
  blocking-wait or background retry. Phase 5 keeps it synchronous and
  surface-on-conflict; queueing is a Phase 6+ feature.
- **No detection of cross-language interface drift.** If unit A is Python
  and unit B is TS calling A's HTTP API, drift in A's URL routes won't be
  caught by AST diff. Drift detection is intra-language only.
