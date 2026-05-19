---
description: AIDLC Orchestrator help. Explains all commands and how to get started.
argument-hint: [command-name]
---

# AIDLC Orchestrator — Help

Start any new feature with:

```
/factory-spec "<request>"
```

## Orchestrator workflow (Claude Code)

The orchestrator uses specialized subagents per stage. Start with:

```
/factory-spec "add JWT auth to the API gateway"
```

This triggers triage (TINY → FastPath, or SMALL+ → full pipeline).

### Full pipeline

```
/factory-spec <request>   →  workspace-scout → requirements-analyst
/factory-plan <run-id>     →  workflow-planner → unit-decomposer
/factory-build <run-id>    →  code-generator × N units + build-test-agent
/factory-review <run-id>   →  4 parallel reviewers → merged report
/factory-ship <run-id>     →  release notes, ADRs, changelog, CI/CD
```

Each command waits for your approval before proceeding. You inspect, approve,
and move to the next stage.

### Fast Path (TINY tier)

For trivial requests (typo, README fix, one-file change), the orchestrator
skips all stages and goes directly to code-generator:

```
/factory-spec "fix typo in README"
→ triage: TINY (score 0)
→ code-generator → commit
→ done. No manifest, no audit, no multi-agent overhead.
```

---

## Command reference

| Command | When to use | What happens |
|---------|-------------|-------------|
| `/factory-onboarding` | First time using the orchestrator | Guided tour of the system |
| `/factory-spec "<request>"` | **Start here** for any new feature | Triages your request, spawns scout + analyst |
| `/factory-plan <run-id>` | After `/factory-spec` completes | Creates execution plan + design units |
| `/factory-build <run-id>` | After plan is approved | Generates code + runs tests in parallel |
| `/factory-review <run-id>` | After build completes | 4 reviewers analyze code in parallel |
| `/factory-ship <run-id>` | After review passes | Release notes, ADRs, changelog |
| `/factory-state <run-id>` | Check progress anytime | Shows current stage, next step, timeline |
| `/factory-resume <run-id>` | Run crashed mid-flight | Picks up from the last completed stage |
| `/factory-replay <run-id> --from <stage>` | Stage produced wrong output | Rolls back and re-runs from that stage |
| `/factory-self "<task>"` | Improve the orchestrator itself | Runs pipeline against orchestrator's own code |
| `/factory-help [command]` | Remember a command | This page |

---

## Monitoring

```bash
# Visual timeline of what ran and how long it took
python3 aidlc-scripts/factory_run.py graph <run-id>

# Approval gate delays
python3 aidlc-scripts/factory_run.py status <run-id> --latency

# Live event feed
python3 aidlc-scripts/factory_run.py tail <run-id> --follow
```

---

## Recovery

| Situation | Solution |
|-----------|----------|
| Run crashed or you closed the session | `/factory-resume <run-id>` |
| A stage produced wrong output | `/factory-replay <run-id> --from <stage>` |
| An agent crashed and left stale locks | `python3 aidlc-scripts/factory_conflict.py release <run-id> --stale --older-than 120` |
| Need to know what happened | `python3 aidlc-scripts/factory_run.py timeline <run-id> --follow` |

---

## Custom subagents

Create your own specialized agents in `.claude/agents/custom/`:

```bash
# Discover available agents
python3 aidlc-scripts/factory_agent_discover.py list
python3 aidlc-scripts/factory_agent_discover.py show lint-audit
```

Custom agents use generic contracts and default to `sonnet` model.
See `README.md` for details.

---

## CLI tools

```bash
# Score a request without spawning agents
python3 aidlc-scripts/factory_triage.py "add healthz" --dry-run

# Validate a handoff contract
python3 aidlc-scripts/factory_validate.py schema.json doc.yaml --strict

# Scan for secrets in handoff files
python3 aidlc-scripts/factory_secretscan.py handoff.yaml
```

---

## Documentation

- `docs/TROUBLESHOOTING.md` — common failures and fixes
- `.aidlc-orchestrator/contracts/REFERENCE.md` — all handoff schemas
- `ORCHESTRATOR-PLAN.md` — full design doc
- `ORCHESTRATOR-SIMPLIFY-PLAN.md` — architecture roadmap
