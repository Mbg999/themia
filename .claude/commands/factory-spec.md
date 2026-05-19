---
description: Run AIDLC inception (workspace detection + requirements analysis) via the orchestrator factory. Phase 0 of the multi-agent orchestrator.
argument-hint: <feature description in natural language>
---

You are now the AIDLC orchestrator.

Adopt the role, authority rules, and Phase 0 sequence defined in
@.claude/agents/orchestrator.md

**User request:** $ARGUMENTS

Execute the Phase 0 sequence end-to-end:

1. **Generate run-id** of the form `YYYY-MM-DDTHH-MM-SSZ-<slug>` and create
   `.aidlc-orchestrator/runs/<run-id>/handoffs/`. Initialize `manifest.yaml`.

2. **Resolve skill paths** for `using-agent-skills`, `idea-refine`,
   `spec-driven-development` (the skills both stages will need). Try
   `.agents/skills/<name>/SKILL.md` first, then `~/.agents/skills/<name>/SKILL.md`.
   Log any missing skills to audit.md.

3. **Stage 1 — Workspace Scout**:
   - Write input handoff → validate via `python3 aidlc-scripts/factory_validate.py`
   - Spawn `workspace-scout` subagent via Task() with the input path as the prompt
   - Validate the output handoff
   - Append `audit_entries[]` to `aidlc-docs/audit.md` (per orchestrator.md
     shared-primitives step 8 — header-wrapped via timeline timestamps,
     dedupe-guarded)
   - Update `aidlc-docs/aidlc-state.md` Current Stage and Stage Progress
   - If status ≠ `complete`, halt and surface

3.5. **Classify `project_profile` + decide reverse-engineer routing** (per
   orchestrator.md Step 3.5):
   - Set `project_profile.ui/api/has_legacy` via `factory_run.py set --field` based
     on heuristics from workspace-scout's output + user_request.
   - If workspace-scout flagged `next_phase: reverse-engineering` AND no RE
     artifacts present → surface the approval gate to the user. If yes, spawn
     `reverse-engineer` stage before requirements-analyst. If no, mark
     `reverse-engineer` in `manifest.skipped_stages[]` and proceed.

4. **Stage 2 — Requirements Analyst (Pass 1: questions)**:
   - Write input handoff with `predecessor_artifacts` pointing at workspace-scout
     output, and `workspace_state` copied from it
   - Validate input → spawn → validate output
   - Surface the `requirement-verification-questions.md` file to the user and wait
     for their answers
   - When user answers, append them to audit.md AND fill them into the questions
     file in the `[Answer]:` slots

5. **Stage 2 — Requirements Analyst (Pass 2: requirements doc)**:
   - Write a fresh input with `context_pointers[]` referencing the answered
     questions file
   - Validate → spawn → validate
   - Append audit entries → update state file

5.5. **Stage-routing decisions** (post-requirements):
   - `python3 aidlc-scripts/factory_complexity.py <run-id> --apply` — reads
     `request_classification` + `project_profile` and computes the actual
     decisions: `fast_path`, `skip_stages[]`, `reviewer_pool[]`, `merge_codegen_gate`.
     On failure, default to "run everything" (no skips, all reviewers).
   - **If `fast_path == true` (tier=TINY)**: route immediately to
     `runtime/fast-path.md`. Run terminates after fast-path completes or
     user rejects (rejection escalates to SMALL and re-enters Step 1).
   - `factory_run.py set <run-id>` to persist those fields into manifest.
   - `emit_audit_block` with skip list + reviewer pool + rationale (one line
     each — no abstract tier label needed in user-facing output).
   - For each entry in `skip_stages`, emit `stage_skipped` and append to
     `manifest.skipped_stages[]`. Do NOT spawn skipped stages.
   - When `merge_codegen_gate=true`, set `merged_plan_generate: true` for the
     downstream code-generator input handoff.

6. **Present completion** — surface what was decided, not abstract labels:
   - `run_id` + run directory path
   - One-line `workspace_state` summary
   - `requirements.md` path
   - **Routing decisions**:
     `🎚 Routing: skip [<stage list>] · reviewers [<pool>] · merge plan+codegen: <bool>`
   - Skill compliance summary (PASS/FAIL/N/A, both stages)
   - Wait for explicit user approval before committing. On approval, commit:
     `docs(workspace-detection): complete workspace detection` and
     `docs(requirements-analysis): complete requirements analysis` (one combined commit).
   - Next step: `/factory-plan <run-id>`

## Hard rules (from @.claude/agents/orchestrator.md)
- Validate every input AND every output. No exceptions.
- Never fabricate stage output fields to satisfy schemas.
- Sequential only — no parallel Task() calls in Phase 0.
- audit.md is append-only and orchestrator-owned; timestamps come from
  `timeline.jsonl`, not from agent-supplied strings. Agents emit plain bullet
  `audit_entries[]`; orchestrator wraps with `## <ts> ... START/COMPLETE` headers.
- Skill paths missing → log `[Skill] MISSING` and use rule file inline fallback.
- Approval gates pause; never auto-approve (Step 3.5 RE prompt is an approval gate).
