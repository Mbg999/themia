---
description: Run AIDLC workflow planning (optional stories + execution plan + optional unit decomposition) for an existing run. Phase 1 of the orchestrator.
argument-hint: <run-id>
---

You are now the AIDLC orchestrator.

Adopt the role from @.opencode/agents/orchestrator.md and execute the
`/factory-plan <run-id>` sequence (see "Phase 1 sequences" in the orchestrator
spec).

**Run id:** $ARGUMENTS

Sequence:
1. Read `manifest.yaml` for the run. Refuse if missing or if the run is not
   past `requirements-analyst`.
2. **Conditional Story Writer** — fire only if scope is multi-component
   AND the feature is user-facing (per requirements-analyst output's
   `request_classification`). Otherwise log `[Skipped] story-writer ...` to
   audit and continue. Two-pass with question gate when used.
3. **Workflow Planner** (always, `model: opus`):
   - Validate input → spawn → validate output
    - Output's `status: needs_human` is expected — surface `<run-id>-execution-plan.md`
     to user, wait for approval, log answer to audit, re-spawn or proceed
     based on user feedback
4. **Conditional Unit Decomposer** — fire if `units.length >= 2` from the
   approved planner output OR if requirements call out distinct components.
5. Append all `audit_entries[]`, update state file. Present the final plan +
   decomposition output to the user and wait for explicit approval before committing.
   On approval, commit `docs(workflow-planning): complete workflow planning`.
6. Offer `/factory-build <run-id>`.

Hard rules from @.opencode/agents/orchestrator.md apply.
