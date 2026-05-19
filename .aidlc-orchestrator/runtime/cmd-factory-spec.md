# `/factory-spec` — Phase 0 sequence

PRIORITY: P2

For `/factory-spec <description>`. Pass `--tier=small` to force SMALL tier and skip routing.

## Step 1 — Init run dir + budget
```
run_id = YYYY-MM-DDTHH-MM-SSZ-<slug>  # UTC timestamp; slug = first 3-4 words, hyphenated
mkdir -p .aidlc-orchestrator/runs/<run-id>/handoffs
```
Create `manifest.yaml` with `{run_id, started_at, user_request, current_stage: workspace-scout, completed_stages: []}`.

## Step 2 — Resolve skill paths (once per run)
Find each required SKILL.md: `.agents/custom-skills/<name>/SKILL.md` → `.agents/skills/<name>/SKILL.md` → `~/.agents/skills/<name>/SKILL.md`. Store in `manifest.skill_paths:`. Log `[Skill] MISSING: <name>` if not found (uses inline fallback).

> **Framework skills** (autoskills-installed) are NOT yet available at spec time —
> they are synced and selected during `/factory-build` Pre-Build Step 0.
> Spec and plan stages use `.agents/custom-skills/` process skills only.

## Step 3 — Workspace Scout (inline)

PRIORITY: P2

Execute `stage/workspace-scout.md` inline (no `Task()`). Follow the
[post-execution loop](spawn-loop.md) for bookkeeping.

Pre-execution (steps 0-1): emit `spawn_start`, knowledge query.
Then execute stage instructions directly — no handoff file, no contract validation.
After execution: lightweight validation (see [`validation.md`](validation.md)),
context compaction (see [`compaction.md`](compaction.md)), audit
append, state update, auto-commit, `spawn_end`, complete-stage, halt-check.

Stage-specific knobs:
- **skills_required**: `[using-agent-skills]`
- **predecessor_artifacts**: none (first stage)
- **approval gate**: none — auto-proceeds on `status: complete`
- **state on success**: `Current Stage: INCEPTION - Workspace Detection (complete)`; manifest `current_stage: requirements-analyst`

## Step 3.5 — Classify `project_profile` + reverse-engineer routing

After workspace-scout completes, classify `project_profile` (ui / api / has_legacy) and decide whether to run `reverse-engineer`. Full spec — classification heuristics, persistence command, audit-bullet format, conditional-skill injection table, RE approval-gate prompt text — lives in [`project-profile.md`](project-profile.md).

Then proceed to Step 4.

## Step 4 — Requirements Analyst (two-pass, inline)

PRIORITY: P2

Execute `stage/requirements-analyst.md` inline (no `Task()`). Follow the
[post-execution loop](spawn-loop.md) for bookkeeping.

**Two-pass**: both passes execute inline. Pass 1 emits answers → surface → user responds → Pass 2.

Pre-execution (steps 0-1): emit `spawn_start`, knowledge query.
Then execute inline. After each pass: lightweight validation, context compaction.
On user answers (between passes): call `emit_audit_block` per [`audit-block.protocol.md` § user_answers_received](../contracts/audit-block.protocol.md).

Stage-specific knobs:
- **skills_required**: `[idea-refine, spec-driven-development, using-agent-skills]`
- **predecessor_artifacts**: workspace-scout's output handoff. Copy its `workspace_state` block into the input.
- **state on Pass 2 success** (Bug B fix — three required mutations, do NOT skip any):
  1. `Current Stage`: `INCEPTION - Requirements Analysis (complete) — awaiting /factory-plan`.
  2. `Stage Progress`: mark `[x] Requirements Analysis — <ISO date>`.
  3. `Extension Configuration` table (upsert per current iteration): parse the answered questions file for `^## Question: (.+) Extension$` headings. Map answer letter → enabled value via the option text: `A → Yes`; `B`/`C` → `Partial` if option text contains "Partial"/"only", else `No`; anything else → `Unknown` (and log warning). Upsert into `## Extension Configuration` table with `Decided At = Current iteration: Requirements Analysis (Answer <letter>) — run_id <run-id>`. Create the table with 3-column shape (`| Extension | Enabled | Decided At |`) if absent. Log `[Orchestrator] Extension Configuration upserted: <ext>=<val>` per row.

## Step 4.5 — Stage-Routing Decisions (once per run, after Pass 2)

Derive concrete pipeline decisions from `request_classification` + `project_profile`. The tier
label is persisted for telemetry; what matters downstream is `fast_path`, `skip_stages[]`,
`reviewer_pool[]`, `merge_codegen_gate`.

1. `factory_complexity.py <run-id> --apply` (on failure default to "run everything": empty skip list, full reviewer pool).
2. Parse JSON output. **If `fast_path == true` (tier=TINY)**: route immediately to
   [`fast-path.md`](fast-path.md) — do NOT proceed to Step 5 or `/factory-plan`. Run terminates
   after fast-path completes or user rejects.
3. `factory_run.py set <run-id> --field complexity_tier=<tier> --field skip_stages='<json>' --field merge_codegen_gate=<bool> --field reviewer_pool='<json>'`. Validate against `shared/complexity-tier.schema.json` (non-blocking warn only). `complexity_tier` is persisted for telemetry but is not the user-facing artifact.
4. `emit_audit_block` with skip list + reviewer pool + one-line rationale per decision.

**Skip enforcement**: for each skipped stage, `emit_audit_block --evt stage_skipped` → append to `manifest.skipped_stages[]` → continue. Do NOT spawn.

**Merged codegen gate**: if `merge_codegen_gate`, set `merged_plan_generate: true` in code-generator input → agent skips plan-approval, outputs `sub_stage: generated`.

## Step 5 — Auto-commit
`git add -A && git commit -m "<type>(<scope>): <description>"` per core-workflow.md. Types: `docs` (plans/requirements), `feat` (code), `build` (build/test). Scope = stage in kebab-case. If git fails, log warning and continue.

## Step 6 — Present completion
Show: run_id, workspace_state (1 line), requirements.md path, **routing decisions** (`skip_stages`, `reviewer_pool`, `merge_codegen_gate`), skill compliance table. Offer `/factory-plan <run-id>`. Do NOT prominently display the abstract `complexity_tier` label — the decisions are the user-visible artifact.
