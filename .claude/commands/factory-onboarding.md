---
description: Walk through the AIDLC orchestrator system. Learn how runs work, what commands to use, and how to recover from failures.
argument-hint: (no arguments needed)
---

# 🏭 AIDLC Orchestrator — Onboarding

This guide walks through the multi-agent factory. If you just want to ship
code, start at step 1. Each section explains the *why* so you understand the
system.

---

## 1. How it works

Use `/factory-spec "<request>"`. A dedicated orchestrator agent spawns
specialized subagents (scout, analyst, code-gen, reviewer, etc.) per stage.

**When to use the orchestrator:**
- Multi-component features (several files, services, or modules)
- Brownfield work (needs reverse-engineering existing code)
- Runs where you want budget caps, crash recovery, or a parallel reviewer pool

---

## 2. Start a run

```
/factory-spec "add JWT auth to the API gateway"
```

The orchestrator:

1. **Triages** your request: TINY (Fast Path) or SMALL/MEDIUM/LARGE (full pipeline)
2. **Generates a run-id** like `2026-05-12T14-23-00Z-jwt-auth-api-gateway`
3. **Spawns workspace-scout** to learn your codebase
4. **Spawns requirements-analyst** to write a spec (may ask you questions)

At the end, you get a `run-id`. Keep it — you'll need it for subsequent commands.

**Fast Path (TINY):** if your request scores 0 complexity signals (e.g. "fix typo"),
the orchestrator goes directly to code-generator and commits. No multi-agent overhead.
You'll see: `🏎️ FAST_PATH completed | 1 file changed | 1 test | commit=abc123`

---

## 3. Plan the work

After `/factory-spec`, you'll have a `run-id` and a `requirements.md`.

```
/factory-plan <run-id>
```

This spawns:
- **workflow-planner** — designs the execution plan
- **unit-decomposer** — splits the work into parallel design units (for complex features)

You'll get a plan with units like `auth-middleware`, `token-verification`, `route-guards`.
Each unit is a chunk of work that can be code-gen'd in parallel.

---

## 4. Build

```
/factory-build <run-id>
```

This is the heavy lifter. It spawns **code-generator** × N units in parallel
waves, then **build-test-agent** × N to verify each one.

The orchestrator enforces:
- **File-glob locks** — two units writing to the same file must wait
- **AST drift detection** — if one unit changes a function another depends on,
  a conflict is flagged for human resolution
- **Budget gates** — pre-flight check before each spawn (ok / downshift / skip / halt)

---

## 5. Review

```
/factory-review <run-id>
```

Fans out 4 reviewers in parallel:
| Reviewer | Focus |
|----------|-------|
| code-quality | correctness, maintainability, readability, testing, design |
| security | OWASP top 10, CWEs, secrets, auth logic |
| performance | Big-O, N+1 queries, caching, bottlenecks |
| simplifier | dead code, over-engineering, unnecessary abstraction |

Results are merged into `aidlc-docs/operations/<run-id>-review-report.md`.

---

## 6. Ship

```
/factory-ship <run-id>
```

Final stage: release notes, ADRs, CHANGELOG update, CI/CD wiring suggestions.

---

## 7. If something goes wrong

| Situation | Command |
|-----------|---------|
| Run crashed mid-stage | `/factory-resume <run-id>` |
| Stage produced wrong output | `/factory-replay <run-id> --from <stage>` |
| Stale locks from dead agent | `python3 aidlc-scripts/factory_conflict.py release <run-id> --stale --older-than 120` |
| Need to see what happened | `python3 aidlc-scripts/factory_run.py graph <run-id>` |
| Model assignment wrong | Edit `.aidlc-orchestrator/budgets/default.yaml` per-stage `model` fields |

If a stage returns `needs_human`, the orchestrator pauses and presents a
structured approval prompt:

```
⏸️  Approval — <Stage>
  [Approve] [Request Changes] [Cancel Layer]
```

You review, decide, and the orchestration continues.

---

## 8. Self-hosting

Want to improve the orchestrator itself? Use:

```
/factory-self "add --stale flag to factory_conflict.py release"
```

This runs the full pipeline against `aidlc-scripts/`, `.claude/agents/`, and
`tests/` — the orchestrator building itself.

---

## Reference

- `/factory-state <run-id>` — current stage, next step, budget, timeline
- `/factory-help` — quick command reference
- `docs/TROUBLESHOOTING.md` — failure modes and fixes
- `.aidlc-orchestrator/contracts/REFERENCE.md` — all handoff schemas
- `ORCHESTRATOR-PLAN.md` — design rationale, phase plan, acceptance criteria
