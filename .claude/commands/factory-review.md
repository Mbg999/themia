---
description: Run AIDLC post-generation reviewer pool (code quality, security, performance, simplification) in parallel. Phase 4 of the orchestrator.
argument-hint: <run-id>
---

You are now the AIDLC orchestrator.

Adopt the role from @.claude/agents/orchestrator.md and execute the
`/factory-review <run-id>` sequence (now **parallel fan-out** per Phase 4).

**Run id:** $ARGUMENTS

Sequence:
1. Read `manifest.yaml`. Refuse if construction isn't complete.
1.5. **Collect framework skills from build** (Pre-Review Step 0.5 per
   `runtime/cmd-factory-review.md`): read `manifest.skill_paths` + all
   `code-generator.*.output.yaml` handoffs; extract skills not in the base set.
   Store as `framework_skill_paths`. Log the list even if empty.
2. **Sequential knowledge queries** per active reviewer; build per-reviewer
   input handoff under `.aidlc-orchestrator/runs/<run-id>/handoffs/reviewer-<x>.input.yaml`
   with reviewer-specific tags and top-5 priors injected into `context_pointers[]`.
   For `reviewer-code`: merge `framework_skill_paths` into the handoff's
   `skills_required[]` and `skill_paths_resolved[]` before writing.
   Validate each input against `reviewer.input.v1.json`.
4. **Parallel spawn** — emit ONE message containing all N (≤4) `Task()` calls.
   This is what makes Phase 4 different from Phase 1.
5. **Sequential post-processing** per reviewer: validate output →
   knowledge save → audit append.
6. **Merge**:
   ```bash
   python3 aidlc-scripts/factory_merge_reviews.py <run-id> [--reviewers <active-set>]
   ```
   Produces `aidlc-docs/operations/<run-id>-review-report.md`.
7. Surface report to user. Approval gate:
   - **Fixes requested** → route units back through `/factory-build <run-id>`
   - **Approved** → auto-commit `docs(review): complete review report`,
     update state, offer `/factory-ship <run-id>`

Hard rules from @.claude/agents/orchestrator.md apply.

**Phase 4 acceptance**: review wall-clock should be ~`max(reviewer wall-clocks)`,
not sum. Track via `manifest.events[]` timestamps and reviewer `cost.wall_clock_min`.
