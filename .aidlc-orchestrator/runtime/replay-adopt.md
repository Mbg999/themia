# Resume & Replay

PRIORITY: P3

Two cold-path entry points that share the Run Manager's `runs/<run-id>/`
infrastructure but are triggered by infrequent commands.

## Resume (`/factory-resume <run-id>`)

Picks up an interrupted run from its last checkpoint.

1. Read `manifest.yaml` from `.aidlc-orchestrator/runs/<run-id>/`.
2. `next_stage_suggestion = manifest.current_stage` (if not in
   `completed_stages[]`), else the next stage in `PHASE_ORDER`.
3. If `manifest.partial_outputs[]` is non-empty, surface to the user with
   two options:
   - **Trust and complete** — accept partial outputs as-is (appends a
     `resume_requested` event to `timeline.jsonl`; proceeds to
     `next_stage_suggestion`).
   - **Re-spawn fresh** — discard partial outputs for the interrupted stage
     (re-queues it; re-spawns from scratch).
4. If `partial_outputs[]` is empty, proceed directly to
   `next_stage_suggestion`. Emit `resume_requested` to `timeline.jsonl`.
5. Log `[RunManager] Resumed run <run-id> from stage <s>` to audit.

## Replay (`/factory-replay <run-id> --from <stage>`)

Re-runs from a chosen stage forward. Non-destructive — prior outputs are
archived, not deleted.

1. Read `manifest.yaml`; validate `<stage>` exists in `completed_stages[]`.
2. Roll `completed_stages[]` back to remove all stages at and after `<stage>`.
   Write via POSIX-atomic tmpfile+rename.
3. For each output handoff being rolled back, copy to
   `handoffs/<original-name>.replay-<ts>.yaml` (preserve originals; never
   delete).
4. Emit `replay_requested` to `timeline.jsonl`.
5. Set `current_stage` to `<stage>` in manifest.
6. Proceed to spawn `<stage>` fresh. Run normally.

The replay archive prefix `.replay-<ts>.yaml` distinguishes archived outputs
from current handoffs.

## Atomicity

- `manifest.yaml` writes: POSIX-atomic via write-to-tmpfile-then-rename
  (prevents partial reads by concurrent callers).
- `timeline.jsonl` writes: append-only, atomic per line (lines are
  newline-delimited JSON; no partial-write risk at OS level).
- Full spec: `aidlc-scripts/factory_run.py` docstring.

## Why this is a separate runtime doc

Resume/Replay execute in < 5% of runs (loaded on demand). This contrasts
with `spawn-loop.md` which is **load-critical** — read on every spawn.
Keeping cold paths in separate runtime files shrank unconditionally-loaded
kernel context by ~78%.
