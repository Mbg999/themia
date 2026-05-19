# FAST_PATH — TINY-tier Execution

PRIORITY: P3

Runs when `factory_complexity.py` returns `fast_path: true` (tier=TINY) after the
requirements-analyst completes. TINY requires both classification dimensions to independently
resolve to their minimum: `scope == "Single File"` AND `complexity == "Trivial"`. Bypasses
**ALL** shared primitives — no timeline.jsonl, no audit.md blocks (except one flat line), no
lock registry, no knowledge saves, no reviewer pool, no ship stage. The git commit IS the audit
trail.

## Execution

1. `factory_complexity.py` already ran — `fast_path: true`, tier = TINY.
2. Build a minimal code-generator input (no contract validation):
   ```json
   {
     "user_request": "<verbatim from /factory-spec>",
     "tier": "TINY",
     "fast_path": true,
     "repo_root": ".",
     "constraints": [
       "produce minimum viable code",
       "TDD required",
       "no architectural decisions",
       "no new files beyond what the request needs"
     ]
   }
   ```
3. Single `Task(subagent_type="code-generator")` spawn with that JSON as prompt — no input handoff file; pass the JSON inline.
4. The code-generator runs Red → Green → Refactor → Commit normally but skips the plan sub-stage and the approval re-spawn. Returns stripped output: `files_changed`, `tests_added`, `commits_made`.
5. Present the diff to the user with a one-line summary:
   ```
   🏎️ FAST_PATH completed | <N> files changed | <N> tests | commit=<sha>
   [Approve] [Reject — escalate to SMALL]
   ```

6. **On approve**: append ONE flat line to `aidlc-docs/audit.md` (create file with header if missing). No `## ` stage headers — just:
   ```
   <ts> TINY score=<n> FAST_PATH | <request (first 80 chars)> | <N> files | commit=<sha>
   ```
   Do NOT write to `aidlc-state.md`. Run terminates.

7. **On reject**: restart the same request as SMALL tier (route to Phase 0 Step 1 with `--tier=small`, run the full pipeline). Append one flat line to `aidlc-docs/audit.md`:
   ```
   <ts> TINY→SMALL ESCALATED | <request (first 80 chars)> | <reason>
   ```
   Then the standard `/factory-spec` flow takes over.

## What FAST_PATH sacrifices

- No replay capability (cannot `/factory-replay` a TINY run).
- No knowledge emission (engram saves skipped).
- No reviewer pool (security / performance / simplifier review skipped).
- No ADRs (ship stage skipped).
- No build-test-agent stage (code-generator runs tests inline via TDD).
- No conflict-resolver locks (single spawn, nothing to conflict with).
- No orchestartor-level tracking; code-generator self-monitors.

## Bailout paths

1. `--tier=small` on `/factory-spec` forces the full pipeline, skipping triage.
2. Triage scores ≥ 2 route to SMALL naturally.
3. User rejects the FAST_PATH diff → one-time auto-escalation to SMALL.

## Why this is a separate runtime doc

FAST_PATH executes in < 10% of runs (loaded on demand). This contrasts with `spawn-loop.md` which is **load-critical** — read on every spawn. Keeping cold paths in separate runtime files shrank unconditionally-loaded kernel context by ~78%.
