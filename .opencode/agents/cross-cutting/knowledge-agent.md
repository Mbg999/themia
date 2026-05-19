---
description: AIDLC Orchestrator's persistent knowledge layer. Project-scoped engram-backed store of patterns, ADRs, antipatterns, and lessons. Queried before each stage spawn (priors → context_pointers); written after each stage return (emitted_knowledge → engram). NOT invoked as a Task() subagent — orchestrator uses engram MCP tools directly per the protocol below.
---

# Knowledge Agent (Phase 3 — active)

> **Architectural note:** the Knowledge Agent is **not** a Task()-spawnable
> subagent. It is a *capability* the orchestrator exercises by calling
> engram MCP tools directly (`mcp__plugin_engram_engram__mem_save`,
> `mcp__plugin_engram_engram__mem_search`, `mcp__plugin_engram_engram__mem_get_observation`).
> This file is the canonical spec for HOW the orchestrator uses engram for
> AIDLC knowledge — not a subagent definition.

## Purpose

Prevent the AIDLC factory from re-learning the same lessons every run.
Decisions, patterns, antipatterns, and lessons are persisted across runs and
across sessions. Each project has its own namespace; cross-project queries
are explicit.

## Storage backend

**Engram, project-scoped.** topic_key convention:
```
aidlc/<project-slug>/<kind>/<title-slug>
```
- `<project-slug>`: derived from repo name, slugified (lowercase, hyphenated,
  no punctuation). Stored in `manifest.yaml` under `project_slug:`.
- `<kind>`: one of `pattern | adr | antipattern | lesson`.
- `<title-slug>`: first 4-6 meaningful words of the title, slugified.

Examples:
- `aidlc/custom-aidlc/pattern/lambda-handler-token-validation`
- `aidlc/custom-aidlc/antipattern/secrets-in-env`
- `aidlc/custom-aidlc/adr/auth-uses-asymmetric-jwt`
- `aidlc/custom-aidlc/lesson/n-plus-one-from-orm-eager-load`

## Knowledge entry shape

Stage agents emit knowledge in `output.emitted_knowledge[]`. Each entry:
```yaml
kind: pattern | adr | antipattern | lesson
title: "Asymmetric JWT validation in Lambda handler"
body: |
  **What**: ...
  **Why**: ...
  **Where**: ...
  **Learned**: ...
tags: [auth, lambda, jwt]
related_artifacts:
  - src/auth/handler.py
  - tests/auth/test_handler.py
confidence: 0.8     # 0.0..1.0; defaults to 0.8 if omitted
```

The schema is enforced by every stage's output contract (v1 from Phase 3).

## Save protocol (post-spawn)

After EVERY stage agent returns and validates, the orchestrator iterates
`output.emitted_knowledge[]` and calls:

```
mem_save(
  title=<entry.title>,
  type="decision" if entry.kind == "adr" else (
    "pattern" if entry.kind == "pattern" else (
      "learning" if entry.kind == "lesson" else
      "discovery"   # antipattern
    )
  ),
  topic_key=f"aidlc/{project_slug}/{kind}/{title_slug}",
  content=<entry.body>,
  scope="project"
)
```

If `mem_save` returns `judgment_required: true` (engram detected a candidate
conflict with prior memory), the orchestrator follows the judgment heuristic:

- **Resolve silently** (call `mem_judge`) when:
  - confidence ≥ 0.7 AND relation is `related | compatible | scoped | not_conflict`
- **Surface to user** when:
  - confidence < 0.7, OR
  - relation is `supersedes | conflicts_with` AND kind is `adr` (decisions)

Log every save to `audit_entries[]` as `[Knowledge] Saved <kind>: <title>`.
Log judgments as `[Knowledge] Conflict <relation> with <prior>`.

## Query protocol (pre-spawn)

Before EVERY stage agent spawn, the orchestrator queries engram for relevant
priors and seeds them into the input handoff's `context_pointers[]`:

```
results = mem_search(
  query=<stage-derived query string>,
  scope="project",
  limit=5
)
```

**Query construction:**
- Base: keywords from the user request (top-N nouns/verbs).
- Stage-conditional augmentation:
  - `requirements-analyst` → add scope + complexity from prior runs
  - `workflow-planner` → query for prior planning patterns
  - `code-generator` → query for unit-relevant patterns + antipatterns
  - `reviewer-security` → query for known security antipatterns + ADRs
  - `reviewer-*` → query for relevant antipatterns
  - `ship-agent` → query for ADRs to roll into release notes

**Result formatting** — each match becomes a context_pointer entry:
```
### [<kind>] <title>
<body>
```
joined with a separator and pasted into `context_pointers[]` as a string.
Total token budget for priors: target ~2,500 tokens (5 priors × ~500 tokens).

If a result has `confidence < 0.5`: filter it out. If it has `deprecated_by`:
filter it out. If `kind == antipattern` AND relevant to current stage:
**always include** regardless of relevance score (antipatterns are cheap to
ignore but expensive to miss).

Log every query to `audit_entries[]` as `[Knowledge] Query <stage>: <N>
priors retrieved`.

## When stages SHOULD emit knowledge

Reminder for stage authors — surface knowledge in your output when:

| Stage | Emit when |
|---|---|
| **code-generator** | Successful slice that solves a recurring problem (`pattern`); approach you considered and rejected with reasoning (`antipattern`). |
| **build-test-agent** | Bug fixed that wasn't obvious from tests (`lesson`); flaky test diagnosed (`lesson`). |
| **reviewer-security** | Vulnerability found — `antipattern` with `confidence: 0.95` (security findings are high-trust). Save the *root cause*, not the specific fix. |
| **reviewer-{code,performance,simplifier}** | Recurring finding (3+ instances in a single review) → `antipattern`. Single-instance findings stay in the review report only. |
| **ship-agent** | Architectural decisions made during the run → `adr` with Michael Nygard format. |
| **workflow-planner** | A decomposition shape that worked well → `pattern`. |
| **requirements-analyst** | A clarity/scope lesson learned (e.g. "always ask about authentication scope when feature touches user data") → `lesson`. |

When in doubt: do NOT emit. Bad priors poison future runs more than missing
priors slow them down. The Knowledge Agent's value comes from high-precision
entries, not high recall.

## Scope: project-scoped, opt-in cross-project

The default is **project-only** — knowledge from project A cannot leak into
project B's queries. To intentionally include cross-project knowledge:
construct the query with multiple `scope` parameters or use the engram
search's project parameter directly. This is a deliberate operator choice,
not a default.

## CodeGraph enrichment (Phase 8)

When `.codegraph/codegraph.db` is present AND a stage emits a `pattern`
or `adr` knowledge entry, the orchestrator enriches it before calling `mem_save`:

1. **Anchor to source** — call `codegraph_node <primary_symbol>` (derived from
   `related_artifacts[]` first source file → primary export name).
   Append canonical source snippet to `body` under `**Source (at emit time):**`.

2. **Caller context** — call `codegraph_callers <primary_symbol>` and append
   `**Caller count at emit time:** <N>` to the entry body.

3. **ADR symbol links** — for `kind: adr`, append codegraph node IDs to
   `related_artifacts[]` as `codegraph://node/<id>`.

**Skip enrichment when:** `kind` is `antipattern` or `lesson`; CodeGraph absent;
`codegraph_node` returns `not_found`.

Log: `[Knowledge] CodeGraph enriched <kind>: <title> — node: <id>, callers: <N>`

## Failure mode

If engram is unavailable (MCP server down, plugin uninstalled), the
orchestrator continues with empty `context_pointers[]` and skips
`mem_save`. Logs `[Knowledge] DEGRADED: engram unavailable, running without
priors`. This keeps the factory operating even when the knowledge layer is
offline.
