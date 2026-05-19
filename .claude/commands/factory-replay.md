---
description: Re-run an AIDLC orchestrator run from a specific stage. Rolls the manifest back, archives output handoffs, and routes to the chosen stage.
argument-hint: <run-id> --from <stage-name>
---

You are now the AIDLC orchestrator.

Adopt the role from @.claude/agents/orchestrator.md.

**Arguments:** $ARGUMENTS

Parse `<run-id>` and the `--from <stage>` value from `$ARGUMENTS`. If
malformed, refuse with a usage hint and stop.

1. Roll the manifest back and archive handoffs:
   ```bash
   python3 aidlc-scripts/factory_run.py replay <run-id> --from <stage>
   ```
   This:
   - Truncates `manifest.completed_stages[]` before `<stage>`
   - Sets `manifest.current_stage = <stage>`
   - Renames each rolled-back stage's `*.output.yaml` to
     `*.replay-<unix-ts>.yaml` (so prior runs are kept for diff/inspection)
   - Emits a `replay_requested` event to `timeline.jsonl`

2. Surface the result to the user — list of `rolled_back` stages and
   `archived_outputs` paths.

3. Spawn the chosen stage per the orchestrator protocol (validate input,
   apply pre-flight gates from Cost Governor + Conflict Resolver, etc.).

**Use cases:**
- A reviewer found a P0 issue that requires re-doing code generation
  for a unit → replay from `code-generator`.
- The user wants to adjust requirements after seeing the plan → replay
  from `requirements-analyst`.
- A schema bump (input or output contract) requires re-running a stage
  with the new format.

**Replay is destructive to the manifest's progress record but non-destructive
to artifacts.** Old outputs are archived, never deleted.

Hard rules from @.claude/agents/orchestrator.md apply.
