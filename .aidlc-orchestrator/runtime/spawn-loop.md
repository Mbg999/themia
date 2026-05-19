# Shared Spawn Loop

PRIORITY: P1

> **Load-critical.** This file is read on every stage spawn (~5.5 KB, ~1.4K tokens). Keep under 200 lines. Cold-path content (FAST_PATH, recovery, replay/adopt, project-profile) belongs in their respective `runtime/*.md` files, NOT here.

Two execution modes: **Full spawn loop** (parallel stages — uses `Task()`) and
**Post-execution loop** (sequential inline stages — no `Task()`). Both produce
identical timeline, audit, and state outcomes.

## Full spawn loop (parallel stages)

Every parallel stage spawn follows this 10-step sequence. Steps 3-5 (handoff
validate → Task() → output validate) are SKIPPED for inline sequential stages.

0. **Timeline event (spawn_start)**: `python3 aidlc-scripts/factory_run.py emit <run-id> --evt spawn_start --stage <stage> --field tokens_estimate=N`

1. **Knowledge query (pre-spawn)**: call `mcp__plugin_engram_engram__mem_search` TWICE — once scoped to `aidlc/<project_slug>/*` (top-5), once to `aidlc/_shared/*` (top-5) if `features.shared_corpus_injection=true`. Inject results (after confidence/deprecation filtering, antipattern boosting) into input handoff's `context_pointers[]` as markdown strings, each tagged with `scope: project` or `scope: shared`. Log `[Knowledge] Query <stage>: <N> project priors + <M> shared priors retrieved` to audit. Full namespace + lifecycle: [`runtime/knowledge-agent.md`](knowledge-agent.md). If engram is unavailable, leave `context_pointers[]` empty and log `[Knowledge] DEGRADED: engram unavailable`.

2. **Model resolution**: `python3 aidlc-scripts/factory_model.py resolve <stage>`. If output is non-empty and not the tool default, add `model_override: <model>` to input handoff. If user passed `--model` on the slash command, use that instead and skip the script.

3. **Validate input handoff** against its JSON Schema contract.

4. **Spawn subagent**: `Task(subagent_type=..., prompt=<input-handoff-path>)`. If input handoff has `model_override`, pass as `model=<model_override>`.

5. **Validate output handoff** against its JSON Schema contract.

6. **Knowledge save (post-return)**: iterate `output.emitted_knowledge[]`. For each entry, call `mcp__plugin_engram_engram__mem_save` with topic_key `aidlc/<project_slug>/<kind>/<title-slug>`, project scope. If response includes `judgment_required: true`, apply the judgment heuristic from `knowledge-agent.md` (silent for related/compatible/scoped; surface low-confidence supersedes/conflicts_with on ADRs). Log `[Knowledge] Saved <kind>: <title>` each.

7. **Append audit_entries[] to `aidlc-docs/audit.md`** (append-only). The orchestrator owns this file — agents emit content but never write headers or timestamps.

   **Spawn-cycle blocks** (the common case): read `ts_start` and `ts_end` from `timeline.jsonl`. Dedupe guard: if the last `## ` section in `audit.md` already has the same `ts_start` AND the same stage label, SKIP. Append:
   ```
   ## <ts_start> <PHASE> - <STAGE LABEL> START
   - [Orchestrator] spawned
   - <agent's audit_entries[] bullets, one per line>

   ## <ts_end> <PHASE> - <STAGE LABEL> COMPLETE
   ```
   `<PHASE>` ∈ `{INCEPTION, CONSTRUCTION, OPERATIONS}`. `<STAGE LABEL>` = stage_id uppercased with `-` → space. Strip rogue `##` headers or fabricated timestamps from agent `audit_entries[]`.

   **Non-spawn blocks** (user decisions, answers received, stage_skipped, orchestrator notes — anything without a spawn_start/spawn_end pair) MUST use `factory_run.py emit_audit_block`. Full protocol: [`contracts/audit-block.protocol.md`](../contracts/audit-block.protocol.md).

8. **Update `aidlc-docs/aidlc-state.md`**: set `Current Stage` and `Stage Progress`.

9. **Auto-commit — DEFERRED**: do NOT commit per-stage. Commits fire ONLY at the command boundary (`cmd-factory-*.md` final step) AFTER explicit user approval. Per-stage commits create unauthorized git history for unapproved artifacts (e.g. story-writer output committed before the user has approved the plan it feeds). See `aws-aidlc-rules/core-workflow.md` § "Auto-Commit on Approval".

10. **Timeline event (spawn_end)**: `python3 aidlc-scripts/factory_run.py emit <run-id> --evt spawn_end --stage <stage> --field status=<s> --field tokens=N --field wall_min=F`

11. **State update**: on `status: complete`, `factory_run.py complete-stage <run-id> <stage> --next-stage <next>`. On `status: failed`, `factory_run.py fail-stage <run-id> <stage> --reason "<text>"`.

12. **Halt or surface**: if `status != complete`: halt and surface. If `status == needs_human`: pause, surface in [`## Structured Approval Format`](../../.claude/agents/orchestrator.md), wait for user response, log to audit, then continue.

## Post-execution loop (inline sequential stages)

Sequential stages (workspace-scout, requirements-analyst, workflow-planner,
ship-agent) execute inline in the orchestrator instead of via `Task()`. Steps
3-5 are skipped. **Context compaction** is mandatory after every inline stage
— discard transient reasoning, preserve only structured outputs and artifacts.

After inline stage execution, run these steps in order:

0. `spawn_start` emit
1. Knowledge query (pre-spawn context injection)
2. **Inline execution**: read `stage/<s>.md` and execute directly — no handoff
   files, no `Task()`, no contract validation.
3. **Lightweight validation**: verify required fields present, artifact paths
   exist, critical structural invariants hold. No JSON Schema validation.
4. **Context compaction**: extract structured outputs → summarize critical
   state → discard transient reasoning. The orchestrator accumulates
   artifacts and summaries, NOT raw cognition.
5. Knowledge save
6. Audit append
7. State update
8. ~~Auto-commit~~ **DEFERRED to command boundary** — see Step 9 in the full spawn loop above. Per-stage commits create unauthorized git history for unapproved artifacts.
9. `spawn_end` emit
10. State update — complete-stage/fail-stage
11. Halt or surface

## Stage-specific deltas

| Stage | Delta |
|-------|-------|
| requirements-analyst | Two-pass: inline execution runs twice (Pass 1 → surface → Pass 2) |
| code-generator | Three sub-stages (plan → generated → approved); each runs full spawn loop with Task() |
| reviewers (pool) | Step 4 spawns all active reviewers in parallel (≤ 4); full spawn loop |
| build-test-agent | Per-unit in parallel per wave (≤ 4); full spawn loop |

## See also
- Audit block protocol: [`contracts/audit-block.protocol.md`](../contracts/audit-block.protocol.md)
- Cold-path recovery: [`runtime/recovery.md`](recovery.md)
