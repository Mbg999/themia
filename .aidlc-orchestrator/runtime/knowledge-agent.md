# Knowledge Agent

PRIORITY: P3

Engram-backed persistent memory (MCP, NOT Task()). Full spec:
[`cross-cutting/knowledge-agent.md`](../../.claude/agents/cross-cutting/knowledge-agent.md).

## Pre-spawn context injection

Before each stage spawn, fetch priors from TWO topic-key namespaces:

| Namespace | Source | Scope |
|---|---|---|
| `aidlc/<project_slug>/<kind>/*` | Per-project observations from this run's history | project |
| `aidlc/_shared/<kind>/*`        | Promoted patterns that recurred across ≥3 projects | shared |

Both feeds emit into `context_pointers[]`. Each pointer carries a `scope`
discriminator (`project` or `shared`) so stage agents can weight project-specific
patterns above shared ones when they conflict.

Top-5 per scope by default (~2.5K tokens for project + ~1.5K for shared = 4K
ceiling). Shared injection is gated by `features.shared_corpus_injection` —
disabled to opt out.

## Post-return persistence

Persist `emitted_knowledge[]` as `aidlc/<project_slug>/<kind>/<title>`. Promotion
to `aidlc/_shared/*` happens out-of-band via
`aidlc-scripts/factory_knowledge_promote.py` — never inline in spawn-loop.

## Degraded mode

Engram unavailable → log `[Knowledge] DEGRADED: engram unavailable`, continue
with empty priors. Stage agents MUST tolerate missing priors.

## Promotion lifecycle

`aidlc-scripts/factory_knowledge_promote.py` (Phase 4.1) runs on demand or
nightly. It:

1. Exports recent observations from engram as JSONL.
2. Clusters by kind + cosine similarity ≥ 0.85 over title+body.
3. Emits a promotion record for any cluster spanning ≥3 distinct projects.
4. The user applies promotions to engram via `mem_save` into `aidlc/_shared/*`.

Provenance pointers (each promotion lists its source `sync_id`s) make
unpromotion straightforward — delete the shared observation, the project-level
sources remain intact.
