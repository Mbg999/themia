# `/factory-build` — Phase 1 build

PRIORITY: P2

Construction phase. **Layer-parallel:** units are topologically sorted by
`depends_on`; each layer runs in parallel (≤ 4 concurrent); layers are
sequential. Locks (file-glob) acquired per-unit before spawn; AST symbol
drift detected post-spawn for Python files.

**Construction Phase Entry Checkpoint** (run BEFORE first layer, per
core-workflow.md): verify audit.md has all Inception entries, state file
`Current Stage` is correct, `aidlc-docs/construction/plans/` exists, and
the execution plan is loaded.

## Pre-Build Step 0 — Skill Sync

Runs ONCE before any unit is spawned.

1. **Sync** — install framework skills via autoskills across all workspace dirs:
   ```bash
   python3 aidlc-scripts/factory_skill_sync.py sync
   ```
   Capture stdout → append each `[Sync]` line to audit.md under `[Skills]` prefix.
   On non-zero exit or Node.js missing: log warning and continue — skill failure
   never blocks a build (universal custom-skills still apply).

2. **Select** — resolve `skill_paths_resolved[]` for all stage input handoffs:
   ```bash
   python3 aidlc-scripts/factory_skill_sync.py select --output json
   ```
   Parse JSON → store `skill_paths_resolved` in `manifest.yaml` under key
   `skill_paths_resolved`. Include this list in every subsequent stage input
   handoff YAML for this run.

3. **Log** to audit.md:
   ```
   [Skills] resolved <N> skills: <name-list>
   [Skills] warnings: <list or "none">
   ```

---

## Step A — Compute unit dependency waves

`factory_graph.py compute <run-id> --apply` (Kahn's algorithm over
`units_decomposed[].dependencies`; writes `manifest.unit_waves`,
`unit_wave_count`, `unit_max_parallelism`).

- Exit 1 (cycle) → log error, fall back to single sequential wave.
- No `unit-decomposer` output → synthesize `unit_waves: [["__monolith__"]]`.
- Validate against `shared/unit-graph.schema.json` (non-blocking warn only).

Emit `CONSTRUCTION - UNIT GRAPH` audit block. "Layer" = "wave".

## Step B — Per-layer execution

For each layer in order:

### B.1 — Sequential per-unit pre-flight (all before spawn)
1. Lock acquire: `factory_conflict.py acquire <run-id> code-generator:<unit> <locks>`. Default: `src/<unit>/**`, `tests/<unit>/**`. exit 1 = drop.
2. AST snapshot (Python): `factory_conflict.py snapshot <run-id> code-generator:<unit> <files>`.
3. Knowledge query: `mem_search` with unit tags; inject top-5 into `context_pointers[]`.
4. Build input handoff `code-generator.<unit>.input.yaml`. Validate.

Active set = units that passed all gates.

### B.1.5 — Wave collision pre-flight (active set ≥ 2 only)
`factory_conflict.py check-wave <run-id> --wave-idx <N>`. `safe: true` → continue.
`safe: false` → drop colliding units to next wave. If wave empties → halt.

### B.2 — Code generator (three sub-stages, parallel per sub_stage)
Code-generator runs `plan` → `generated` → `approved`. For each sub_stage:
1. Parallel `Task(subagent_type="code-generator", ...)` in ONE message (≤ 4).
2. Wait for all returns. Per-unit post-processing (any order): validate output →
   AST drift check → knowledge save → audit append.
3. If AST drift conflict written, surface BEFORE approval gate.
4. Approval gate: surface ALL units. User can approve all, reject specific units
   (re-plan with revised context), or cancel layer.

### B.3 — Build & test (parallel per unit, after all reach `approved`)
Parallel `Task(subagent_type="build-test-agent", ...)` in ONE message (≤ 4).
Per-unit post-processing same as B.2. Approval gate: surface all summaries.

### B.4 — Release locks (always — leaks block future runs)
```bash
python3 aidlc-scripts/factory_conflict.py release <run-id> code-generator:<unit>
```

### B.5 — Per-unit auto-commits
- `feat(<unit-name>): generate <unit> code`
- `build(<unit-name>): complete build and test`

## Step C — After all layers
- Set `Current Stage: CONSTRUCTION - Complete`.
- Present per-unit summary + offer `/factory-review <run-id>`.

## Concurrency cap
Phase 5 honors cap of 4. Batch >4 units within a layer; lock acquire+release per batch.
