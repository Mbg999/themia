---
description: Run AIDLC construction (per-unit code generation + build/test) for an existing run. Layer-parallel per Phase 5 — independent units run in parallel; layers sequential.
argument-hint: <run-id>
---

You are now the AIDLC orchestrator.

Adopt the role from @.opencode/agents/orchestrator.md and execute the
`/factory-build <run-id>` sequence (now **layer-parallel** per Phase 5).

**Run id:** $ARGUMENTS

Sequence:
1. Read `manifest.yaml`. Refuse if missing or if `workflow-planner` hasn't
   completed with user approval.
2. **Construction Phase Entry Checkpoint** (per core-workflow.md MANDATORY):
   audit.md has Inception entries; aidlc-state.md Current Stage correct;
    `aidlc-docs/construction/plans/` exists; `<run-id>-execution-plan.md` loaded.
3. **Pre-Build Step 0 — Skill Sync** (once, before any unit is spawned):
   a. Run sync:
      ```bash
      python3 aidlc-scripts/factory_skill_sync.py sync
      ```
      Capture stdout → append each `[Sync]` line to audit.md under `[Skills]` prefix.
      On non-zero exit or Node.js missing: log warning and continue — skill failure
      never blocks a build (universal custom-skills still apply).
   b. Run select:
      ```bash
      python3 aidlc-scripts/factory_skill_sync.py select --output json
      ```
      Parse JSON → store `skill_paths_resolved` list in `manifest.yaml`. Include
      this list in every subsequent stage input handoff YAML for this run.
   c. Log to audit.md:
      ```
      [Skills] resolved <N> skills: <name-list>
      [Skills] warnings: <list or "none">
      ```
4. **Topo-sort `manifest.units[]`** by `depends_on` into layers. Layer 0 = no
   deps; Layer N = deps all in layers < N. Monolith → single virtual unit.
5. **For each layer (sequential)**, run the parallel construction protocol:
   a. **Pre-flight per unit (sequential, cheap)** — budget gate, lock acquire
      (`factory_conflict.py acquire`), AST snapshot (Python only), knowledge
      query, build+validate input handoff.
   b. **Three sub-stages, parallel per sub_stage** —
      `plan` → `generated` → `approved`. For each:
        - Single message with N parallel `Task(subagent_type=code-generator, ...)`
          calls (N = active set, ≤ 4)
        - Wait for all
        - Per-unit post-processing: validate output, AST drift check
          (`factory_conflict.py check-symbols`), budget deduct, knowledge save,
          audit append
        - Surface any drift conflicts BEFORE the approval gate
        - Consolidated approval gate (plan + generated only)
   c. **Build & Test parallel** — single message with N parallel
      `Task(subagent_type=build-test-agent, ...)` calls; per-unit
      post-processing; consolidated approval gate.
   d. **Release locks** — `factory_conflict.py release` per unit. Always
      release, even on failure.
   e. **Per-unit commits** — only after the consolidated approval gate clears:
      `feat(<unit>): generate <unit> code` and `build(<unit>): complete build and test`.
6. After all layers: set `Current Stage: CONSTRUCTION - Complete`.
7. Present + offer `/factory-review <run-id>`.

Hard rules from @.opencode/agents/orchestrator.md apply.

**Concurrency cap: 4.** If a layer has > 4 units, batch them (4 at a time)
within the layer.

**Conflict resolution (Phase 5)**: escalation-only. On path collision or
interface drift, surface to user; user re-plans, manually merges, or cancels.
Full protocol: `.opencode/agents/cross-cutting/conflict-resolver.md`.
