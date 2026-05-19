# Custom subagents

PRIORITY: P3

Spawn any agent from `.claude/agents/custom/` via the standard spawn loop
([`spawn-loop.md`](spawn-loop.md)).
Discovery: `python3 aidlc-scripts/factory_agent_discover.py list`.
Contracts: `custom-agent.{input,output}.v1.json`. Model: `custom-agent` entry
in `budgets/default.yaml` (`sonnet`).
