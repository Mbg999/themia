<!-- AIDLC-ORCHESTRATOR-POINTER -->
## AIDLC Orchestrator (multi-agent factory mode)

This project ships with the AIDLC orchestrator. To run the multi-agent factory:

- `/factory-onboarding` — guided tour of the orchestrator system
- `/factory-help [command]` — quick command reference
- `/factory-state <run-id>` — current stage, next step, budget, timeline
- `/factory-self <task>` — run the orchestrator on its own codebase
- `/factory-spec <feature>` — workspace scout + (reverse-engineer) + requirements + (stories) + plan
- `/factory-plan` — decompose plan into per-unit specs (multi-component features only)
- `/factory-build` — layer-parallel code generation with file-glob locks + AST symbol drift checks
- `/factory-review` — parallel reviewer pool (code, security, performance, simplifier)
- `/factory-ship` — release notes, ADRs, CI/CD wiring, CHANGELOG, migration plan
- `/factory-resume <run-id>` — resume an interrupted run (or adopt a legacy `aidlc-docs/` project)
- `/factory-replay <run-id> --from <stage>` — re-run from a specific stage

Roles, contracts, budgets, and parallelism rules: see `.claude/agents/orchestrator.md`,
`.aidlc-orchestrator/contracts/`, and `.aidlc-orchestrator/budgets/default.yaml`.
Design rationale and phase plan: `ORCHESTRATOR-PLAN.md` in the AIDLC source repo.
