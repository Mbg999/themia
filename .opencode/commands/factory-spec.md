---
description: Run AIDLC inception (workspace detection + requirements analysis) via the orchestrator factory. Phase 0 of the multi-agent orchestrator.
argument-hint: <feature description in natural language>
---

You are now the AIDLC orchestrator.

Adopt the role, authority rules, and Phase 0 sequence defined in
@.opencode/agents/orchestrator.md

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

6. **Present completion**:
   - Show run_id, run directory path
   - Show `workspace_state` summary (one line)
   - Show `requirements.md` path
   - Show skill compliance summary (PASS/FAIL/N/A per skill, both stages)
   - Wait for explicit user approval before committing. On approval, commit:
     `docs(workspace-detection): complete workspace detection` and
     `docs(requirements-analysis): complete requirements analysis` (one combined commit).
   - Offer next step: `/factory-plan <run-id>` (wired in Phase 1; for now,
     remind the user that Phase 0 stops here)

## Hard rules (from @.opencode/agents/orchestrator.md)
- Validate every input AND every output. No exceptions.
- Never fabricate stage output fields to satisfy schemas.
- Sequential only — no parallel Task() calls in Phase 0.
- audit.md is append-only and orchestrator-owned; timestamps come from
  `timeline.jsonl`, not from agent-supplied strings. Agents emit plain bullet
  `audit_entries[]`; orchestrator wraps with `## <ts> ... START/COMPLETE` headers.
- Skill paths missing → log `[Skill] MISSING` and use rule file inline fallback.
- Approval gates pause; never auto-approve (Step 3.5 RE prompt is an approval gate).
