# Failed→Skipped Recovery

PRIORITY: P3

Runs when a stage spawn returns `status: failed`. Non-critical stages MAY be
skipped; critical stages MUST halt.

## Critical vs non-critical

| Critical (MUST halt) | Non-critical (MAY skip) |
|---|---|
| `workspace-scout` | `reverse-engineer` |
| `requirements-analyst` | `story-writer` |
| `workflow-planner` | `unit-decomposer` |
| `code-generator` | `reviewer-code`, `reviewer-security` |
| `build-test-agent` | `reviewer-performance`, `reviewer-simplifier` |

Skipping a critical stage corrupts the run — `aidlc-state.md` will be missing
a required entry and downstream stages will fail on validation.

## Sequence on non-critical failure

1. Emit `spawn_end status=failed` as usual (preserves diagnostic trail in
   `timeline.jsonl`).
2. Call `emit_audit_block` per `audit-block.protocol.md § stage_skipped`:
   ```bash
   python3 aidlc-scripts/factory_run.py emit_audit_block <run-id> \
       --evt stage_skipped --stage <stage-id> --phase <PHASE> \
       --label "<STAGE LABEL> SKIPPED (non-critical failure)" \
       --field reason="spawn failed" \
       --bullet "<failure summary>"
   ```
3. `factory_run.py set <run-id> --field skipped_stages='[...]'`
   (read current list, append `<stage>`, write back — POSIX-atomic via tmpfile+rename).
4. Set `current_stage` to NEXT in manifest and proceed.

After both `spawn_end status=failed` AND `stage_skipped` exist in
`timeline.jsonl`, all three views agree (timeline / manifest / audit).

## On critical-stage failure

Do NOT skip. Emit `stage_failed` and halt:
```bash
python3 aidlc-scripts/factory_run.py fail-stage <run-id> <stage> \
    --reason "<failure summary>"
```
Surface the failure to the user. The run cannot continue without human
intervention.

## Why this is a separate runtime doc

Stage failure occurs in < 10% of runs (loaded on demand). This contrasts with `spawn-loop.md` which is **load-critical** — read on every spawn. Keeping cold paths in separate runtime files shrank unconditionally-loaded kernel context by ~78%.
