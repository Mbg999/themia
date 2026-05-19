# `/factory-plan` — Phase 1 plan

PRIORITY: P2

Inception phase, post-requirements. Produces the execution plan and
(optional) decomposes into units.

Assume `<run-id>` points at an existing manifest. If missing, refuse
("run not found — start with `/factory-spec` first").

1. **Story Writer (conditional)** — skip when ANY of:
   - `manifest.skip_stages[]` contains `story-writer` (set by ComplexityGov)
   - `requirements-analyst` output's `request_classification.scope` ∉ `{Multiple Components, System-wide, Cross-system}`
   - The user request does not involve user-facing flows

   When skipping, follow complexity-gate skip enforcement. Otherwise execute
   `stage/story-writer.md` inline per the [post-execution loop](spawn-loop.md).
   Predecessor: requirements-analyst output.

2. **Workflow Planner (always)** — `model: opus`. Required. Execute
   `stage/workflow-planner.md` inline per the [post-execution loop](spawn-loop.md).
   Predecessors: requirements + (if present) stories. The planner emits
   `status: needs_human` after producing the plan; on user response, call
   `emit_audit_block` per [`audit-block.protocol.md` § workflow-planner gate](../contracts/audit-block.protocol.md).

3. **Unit Decomposer (conditional)** — skip when ANY of:
   - `manifest.skip_stages[]` contains `unit-decomposer` (set by ComplexityGov)
   - The approved plan enumerates < 2 units AND requirements do not call out distinct services/components

   When skipping due to ComplexityGov, follow complexity-gate skip enforcement.
   Otherwise execute `stage/unit-decomposer.md` inline per the [post-execution loop](spawn-loop.md).

4. Auto-commit `docs(workflow-planning): complete workflow planning` and update
   state. Present completion + offer `/factory-build <run-id>`.

> **Framework skills** are synced at `/factory-build` Pre-Build Step 0, not here.
> Plan stages use `.agents/custom-skills/` process skills only.
