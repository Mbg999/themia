---
description: Run AIDLC ship stage — release notes, ADRs, CHANGELOG, version proposal, optional CI/CD wiring and migration plan. Final stage of the orchestrator.
argument-hint: <run-id>
---

You are now the AIDLC orchestrator.

Adopt the role from @.claude/agents/orchestrator.md and execute the
`/factory-ship <run-id>` sequence.

**Run id:** $ARGUMENTS

Sequence:
1. Read `manifest.yaml`. Refuse if review hasn't completed with user approval.
2. **ship-agent** — spawn with `predecessor_artifacts` = all prior outputs +
   the merged review report. Pass `manifest.project_profile` so the agent
   knows whether to load `deprecation-and-migration*` (when `has_legacy: true`).
3. Validate output. Expected fields include `version_proposal` and `adr_count`.
4. If `status: needs_human` (because the version bump or release plan needs
   user OK): surface, wait, log answer.
5. Append audit entries, update state file:
   `Current Stage: OPERATIONS` (or `CONSTRUCTION - Complete` if user opts
   not to deploy).
6. Auto-commit `docs(ship): release prep complete`.
7. Present final summary:
   - All stages with skill-compliance recap
   - Version proposal + ADR count
   - Release notes path
   - "Ready to push: review the commits before `git push`"

Hard rules from @.claude/agents/orchestrator.md apply.
**This agent does NOT push tags or remote branches.** User pushes manually.
