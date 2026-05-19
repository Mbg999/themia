# Conflict Resolver

PRIORITY: P3

`factory_conflict.py` — lock registry + AST drift detection. Full spec:
[`cross-cutting/conflict-resolver.md`](../../.claude/agents/cross-cutting/conflict-resolver.md).

| Failure mode | Detection point |
|---|---|
| Path collision (overlapping file-glob locks) | `acquire` |
| Interface drift (Python public-symbol change) | `check-symbols` |

Resolution: surface conflict record to user (re-plan / merge / cancel).
Holder naming: `<stage>:<unit>`. Always `release` in finally.
