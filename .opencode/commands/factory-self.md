---
description: Run the AIDLC orchestrator on its own codebase. Use this to add features, fix bugs, or refactor the orchestrator scripts using the factory pipeline itself.
argument-hint: <feature description>
---

You are now the AIDLC orchestrator in SELF-HOSTING mode.

**User request:** $ARGUMENTS

This run targets the orchestrator's **own codebase** at the repo root.
Treat `aidlc-scripts/`, `.opencode/agents/`, and `tests/` as the workspace being developed.

## Self-hosting rules

1. **Workspace scope** is limited to these directories:
   - `aidlc-scripts/` — factory Python scripts
   - `.opencode/agents/` — stage subagent definitions
   - `.aidlc-orchestrator/contracts/` — handoff schemas
   - `tests/` — test suite

2. **Design units** map to individual scripts or agent files. For example:
   - "Add --stale flag to factory_conflict.py" → 1 design unit
   - "Add version-locking to factory_validate.py and factory_run.py" → 2 design units

3. **Validation** uses existing test suite:
   ```
   python3 -m pytest tests/ --tb=short
   ```

4. **Review** focuses on test coverage and backward compatibility.

5. **The commit** includes the update to `docs/TROUBLESHOOTING.md` if the change
   introduces a new failure mode.

6. **No `/factory-ship` stage** — self-hosting runs skip ship-agent. The
   changelog entry is written directly.

Proceed with the standard `/factory-spec` flow (triage → stages → review → commit)
applying the scope constraints above.
