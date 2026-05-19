# Project-Profile Classification & Reverse-Engineer Routing

PRIORITY: P3

Orchestrator runtime spec for **Step 3.5** of `/factory-spec`. Runs after `workspace-scout` completes, before any further stage spawns. Both decisions read from `workspace-scout.output.yaml`.

## A. Classify `project_profile` (Bug #8 fix — gates conditional-skill loading)

Read `workspace-scout.output.yaml.workspace_state` and the original `user_request`. Apply each flag independently:

**`ui = true` iff** EITHER:
- `workspace_state.programming_languages` contains `TypeScript|JavaScript|TSX|JSX` AND `workspace_state.project_structure` matches `/SPA|frontend|React|Vue|Svelte|Angular|Next|Nuxt|web/i`, OR
- the workspace's `package.json` declares a UI framework dependency (`react`/`vue`/`svelte`/etc.)

**`api = true` iff** EITHER:
- the user_request matches `/endpoint|route|REST|GraphQL|API|webhook|\/[a-z][a-z0-9_-]+/i`, OR
- the workspace has `express`/`fastify`/`hono`/`nestjs`/`fastapi`/`flask`/`django` in `package.json`/`pyproject.toml`/etc.

**`has_legacy = true` iff** EITHER:
- `workspace_state.reverse_engineering_artifacts_present == true`, OR
- the user_request matches `/migrat|refactor|deprecat|legacy|rewrite|port/i`

**Persist:**
```bash
python3 aidlc-scripts/factory_run.py set <run-id> \
    --field project_profile.ui=<true|false> \
    --field project_profile.api=<true|false> \
    --field project_profile.has_legacy=<true|false>
```

**Audit**: append a single bullet to the NEXT stage's audit block (NOT a standalone header):
`[Orchestrator] Classified project_profile: ui=<bool>, api=<bool>, has_legacy=<bool>`

## Conditional-skill injection (downstream consumer)

When building input handoffs for `code-generator`, `build-test-agent`, and `ship-agent`, read `manifest.project_profile` and add to `skills_required[]`:

| Flag | Affected stage(s) | Skill to add |
|---|---|---|
| `ui: true` | `code-generator` | `frontend-ui-engineering` |
| `ui: true` | `build-test-agent` | `browser-testing-with-devtools` |
| `api: true` | `code-generator` | `api-and-interface-design` |
| `has_legacy: true` | `ship-agent` | `deprecation-and-migration` |

Resolve the matching `SKILL.md` path and add to `skill_paths_resolved[]`. If the skill file isn't found, log `[Skill] MISSING: <name> (conditional)` and continue — the stage's rule file has an inline fallback.

## B. Reverse-engineer routing (Bug #9 fix)

**If** `workspace_state.next_phase == "reverse-engineering"` **AND** `workspace_state.reverse_engineering_artifacts_present == false` **→** surface the approval gate (do NOT silently skip):

```
⏸️  Reverse-Engineer Recommendation

Workspace Scout detected:
  - project_type: brownfield (existing code present)
  - reverse_engineering_artifacts_present: false

Running `reverse-engineer` first produces:
  - aidlc-docs/inception/reverse-engineering/<run-id>-business-overview.md
  - architecture.md, code-structure.md, api-docs.md, component-inventory.md
  - interaction-diagrams.md, tech-stack.md, dependencies.md

Recommended for: major refactors, new modules touching existing systems,
                 or any change where requirements-analyst would benefit from
                 codebase context.

Skip-OK for: small features (a single endpoint, a config change, doc-only).

Run reverse-engineer now? [Y/n]
```

Use `AskUserQuestion` with options:
- `"Run reverse-engineer first (recommended for big changes)"`
- `"Skip and go straight to requirements-analyst (OK for small features)"`

On user response, call `emit_audit_block` per [`audit-block.protocol.md` § reverse-engineer gate](../contracts/audit-block.protocol.md).

**On approve**: spawn `reverse-engineer` via shared spawn loop. On completion, append to `manifest.completed_stages[]`, set `current_stage: requirements-analyst`.

**On reject**: `factory_run.py set <run-id> --field skipped_stages='[..., "reverse-engineer"]'` (read-modify-write).

**Else** (greenfield, or brownfield-with-RE-artifacts already present): no prompt; proceed directly to Step 4.

## Why this is a separate runtime doc

Project-profile classification runs once per `/factory-spec` invocation (loaded on demand). This contrasts with `spawn-loop.md` which is **load-critical** — read on every spawn. Keeping cold paths in separate runtime files shrank unconditionally-loaded kernel context by ~78%.
