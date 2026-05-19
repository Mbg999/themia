# Runtime Architecture

PRIORITY: P1

Reference document. Every runtime file may reference `index.md §X` instead of
duplicating shared rules.

---

## §0 Runtime Principles

1. Sequential cognition remains continuous
2. Parallel cognition is isolated
3. The orchestrator owns state transitions
4. Stage agents own domain cognition
5. Runtime bookkeeping is independent from execution isolation
6. Raw chain-of-thought never survives stage transitions; compact reasoning
   summaries (tradeoff rationale, constraints, rejected alternatives) MAY
   survive when operationally necessary
7. Validation strictness scales with isolation boundaries

## §1 Execution model

Two modes:

| Mode | Mechanism | Bookkeeping | Validation | Used by |
|---|---|---|---|---|
| Full spawn | `Task()` spawn | Full 13-step | JSON Schema | factory-build, factory-review |
| Post-execution | Inline in orchestrator | Steps 0-2, 6-13 | Lightweight | All other stages |

Full spec: [`spawn-loop.md`](spawn-loop.md).

## §2 Execution boundary rules

A stage MUST use `Task()` when ANY are true:
- parallel execution exists
- independent retry semantics are required
- reviewer independence is required
- speculative execution is beneficial
- lock ownership must be isolated

A stage SHOULD execute inline when:
- execution is strictly sequential
- outputs feed directly into the next cognition step
- isolation provides no correctness benefit
- runtime overhead dominates execution cost

Currently: `/factory-build` and `/factory-review` use `Task()`. All others inline.

## §3 Manifest.yaml shape

```yaml
run_id: YYYY-MM-DDTHH-MM-SSZ-<slug>; started_at: <ISO8601>; user_request: "<verbatim>"
current_stage: <stage>; completed_stages: []; project_slug: <repo-slug>
project_profile: {ui: bool, api: bool, has_legacy: bool}
skill_paths: {<name>: <resolved path>}
```

## §4 Runtime file index

| File | Priority | Purpose |
|---|---|---|
| `index.md` | P1 | Architecture reference (this file) |
| `spawn-loop.md` | P1 | Stage spawn protocol (full + post-execution) |
| `cmd-factory-spec.md` | P2 | `/factory-spec` procedure |
| `cmd-factory-plan.md` | P2 | `/factory-plan` procedure |
| `cmd-factory-build.md` | P2 | `/factory-build` procedure |
| `cmd-factory-review.md` | P2 | `/factory-review` procedure |
| `cmd-factory-ship.md` | P2 | `/factory-ship` procedure |
| `fast-path.md` | P3 | TINY tier execution |
| `recovery.md` | P3 | Failed→skipped recovery |
| `replay-adopt.md` | P3 | Resume / replay |
| `project-profile.md` | P3 | Profile classification + RE routing |
| `run-manager.md` | P3 | Run Manager reference |
| `conflict-resolver.md` | P3 | Conflict Resolver reference |
| `knowledge-agent.md` | P3 | Knowledge Agent reference |
| `custom-subagents.md` | P3 | Custom subagents reference |
| `validation.md` | P3 | Lightweight validation rules |
| `compaction.md` | P3 | Context compaction rules |
| `skill-protocol.md` | P4 | Skill execution protocol |
| `audit-lifecycle.md` | P4 | Audit log lifecycle |
| `extension-loading.md` | P4 | Extension loading protocol |
