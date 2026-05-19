---
description: AIDLC Orchestrator help. Explains all commands and how to get started.
argument-hint: [command-name]
---

# AIDLC Orchestrator — Help

Start any new feature with:

```
/factory-spec "<request>"
```

## Orchestrator workflow

```
/factory-spec "add JWT auth"
  → triage → scout → analyst → plan → build → review → ship
```

### Full pipeline

| Step | Command | What happens |
|------|---------|-------------|
| 1 | `/factory-spec "<request>"` | **Start here.** Triage + scout + requirements |
| 2 | `/factory-plan <run-id>` | Execution plan + unit decomposition |
| 3 | `/factory-build <run-id>` | Parallel code-gen + build-test per unit |
| 4 | `/factory-review <run-id>` | 4 parallel reviewers → merged report |
| 5 | `/factory-ship <run-id>` | Release notes, ADRs, changelog |

### Fast Path

Trivial requests skip all stages:
```
/factory-spec "fix typo"  →  code-generator  →  commit  →  done
```

---

## All commands

| Command | What it does |
|---------|-------------|
| `/factory-onboarding` | Guided tour of the system |
| `/factory-spec "<request>"` | **Start here.** Score + spawn stages |
| `/factory-plan <run-id>` | Execution plan + design units |
| `/factory-build <run-id>` | Parallel code-gen + build-test |
| `/factory-review <run-id>` | 4 parallel reviewers |
| `/factory-ship <run-id>` | Release notes, ADRs, changelog |
| `/factory-state <run-id>` | Current stage, next step |
| `/factory-resume <run-id>` | Resume crashed run |
| `/factory-replay <run-id> --from <stage>` | Re-run from a stage |
| `/factory-self "<task>"` | Run on own codebase |
| `/factory-help [command]` | This page |

---

## Monitoring

```bash
python3 aidlc-scripts/factory_run.py graph <run-id>
python3 aidlc-scripts/factory_run.py tail <run-id> --follow
```

---

## Recovery

| Situation | Action |
|-----------|--------|
| Crash | `/factory-resume <run-id>` |
| Bad output | `/factory-replay <run-id> --from <stage>` |
| Stale locks | `python3 aidlc-scripts/factory_conflict.py release <run-id> --stale --older-than 120` |

---

## Custom subagents

Create your own agents in `.opencode/agents/custom/`:

```bash
python3 aidlc-scripts/factory_agent_discover.py list
```

---

## Docs

- `docs/TROUBLESHOOTING.md`
- `.aidlc-orchestrator/contracts/REFERENCE.md`
- `ORCHESTRATOR-PLAN.md`
