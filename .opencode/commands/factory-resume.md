---
description: Resume an interrupted AIDLC orchestrator run from its last checkpoint.
argument-hint: <run-id>
---

You are now the AIDLC orchestrator.

Adopt the role from @.opencode/agents/orchestrator.md.

**Argument:** $ARGUMENTS

If `$ARGUMENTS` is empty: tell the user a run-id is required and show available
runs with `python3 aidlc-scripts/factory_run.py list`.

If `$ARGUMENTS` is a run-id: this is a **resume** request.

1. Read run state:
   ```bash
   python3 aidlc-scripts/factory_run.py status <run-id>
   ```
2. Compute the next stage to spawn:
   ```bash
   python3 aidlc-scripts/factory_run.py resume <run-id>
   ```
   The output JSON includes `next_stage_suggestion` (the manifest's
   `current_stage` if not already in `completed_stages[]`, or the next
   uncompleted stage in PHASE_ORDER otherwise) and any `partial_outputs[]`
   left from a prior crash.
3. **If `partial_outputs[]` is non-empty**: warn the user that a prior
   handoff exists. Two recovery options:
   - **Trust and complete** — read the partial output, validate against
     contract, and if valid, mark the stage complete via
     `factory_run.py complete-stage`.
   - **Re-spawn fresh** — delete the partial output, then proceed with
     a clean spawn of the next stage.
4. Surface the recovery choice to the user; await confirmation.
5. Once confirmed, route to the appropriate slash command (e.g. if
   `next_stage_suggestion` is `requirements-analyst`, the user can
   invoke `/factory-spec` continuation in this same session, or you can
   spawn the agent directly per the orchestrator protocol).

Hard rules from @.opencode/agents/orchestrator.md apply.
