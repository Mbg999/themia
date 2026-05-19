# Skill Execution Protocol

PRIORITY: P4

Skills are the primary enforcement mechanism for quality and process.

## Skill locations (search order, first-found wins)
- `<repo>/.agents/custom-skills/<skill-name>/SKILL.md` (project-specific, always committed)
- `<repo>/.agents/skills/<skill-name>/SKILL.md` (installed by `factory_skill_sync.py sync`)
- `~/.agents/skills/<skill-name>/SKILL.md` (user-global fallback)

**How `skill_paths_resolved[]` is populated**: at `/factory-build` Pre-Build Step 0,
`factory_skill_sync.py select` runs autoskills across all workspace directories (monorepo
support), consolidates framework skills to `.agents/skills/`, then returns the full path
list. Stages at spec/plan time use `.agents/custom-skills/` only (process skills).
`factory_autoskills.py` handles private/internal skills from `skill-sources.yaml` and
coexists with `factory_skill_sync.py` — both write to `.agents/skills/`.

## Skill anatomy
Every skill from addyosmani/agent-skills has: **Overview**, **When to Use**,
**Process**, **Common Rationalizations**, **Red Flags**, **Verification**.

## Execution protocol (MANDATORY)

1. **LOAD** — Read each `<skill_path>/SKILL.md` from `skill_paths_resolved[]`.
2. **FOLLOW** — Execute the skill's Process steps in order.
3. **CHECK** — Apply anti-rationalization table. If tempted to skip, answer is NO.
4. **VERIFY** — Produce concrete evidence per Verification section.
5. **LOG** — `[Skill] Executed: <skill-name> (<Stage>) — PASS|FAIL` in audit.
6. **BLOCK** — If verification fails → stage cannot complete. Fix first.

**Missing skill file**: Use inline fallback from rule file. Log warning.
**Anti-bypass**: "I'll do it later" / "it's obvious" = rationalization. Must produce evidence.

## Skills by phase

| Phase | Skills |
|---|---|
| Define | `idea-refine`, `spec-driven-development` |
| Plan | `planning-and-task-breakdown` |
| Build | `incremental-implementation`, `tdd`, `source-driven-development`, `frontend-ui-engineering`*, `api-and-interface-design`* |
| Verify | `tdd`, `browser-testing-with-devtools`*, `debugging-and-error-recovery` |
| Review | `code-review-and-quality`, `security-and-hardening`, `performance-optimization`, `code-simplification` |
| Ship | `shipping-and-launch`, `git-workflow`, `ci-cd`, `documentation-and-adrs`, `deprecation-and-migration`* |

## Compliance summary
Every stage completion MUST include:
```markdown
### Skill Compliance
| Skill | Status | Evidence |
|-------|--------|----------|
| incremental-implementation | ✅ PASS | Tests green, atomic commits |
```
