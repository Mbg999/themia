---
name: codegraph-aware-exploration
description: When .codegraph/ exists in the workspace, prefer codegraph_* MCP tools over grep/glob/Read for any symbol lookup, call-graph traversal, or impact analysis. Universal skill — applies to every stage agent.
---

# Skill: codegraph-aware-exploration

## Purpose

Replace O(N) grep/glob/Read scans with O(1) graph queries when the project
has been indexed. Upstream benchmarks show 92% fewer tool calls and 71% faster
contextualization on real-world codebases.

## Process

### Step 1 — Detect

Check for `.codegraph/codegraph.db` at project root:

```bash
test -f .codegraph/codegraph.db && echo "indexed" || echo "not-indexed"
```

- **Not indexed** → log `[CodeGraph] not initialized — falling back to grep/Read` and STOP.
  The stage proceeds normally using grep/glob/Read. Do NOT fail.
- **Indexed** → log `[CodeGraph] active — routing symbol queries through graph`.
  Continue to Step 2.

Also check backend:
```bash
codegraph status --json 2>/dev/null | python3 -c "import sys,json; s=json.load(sys.stdin); print(s.get('backend','unknown'))" 2>/dev/null
```
If backend is `wasm`: log `[CodeGraph] backend: wasm — 5x slower than native; prefer native install`.

### Step 2 — Route queries through the decision table

When CodeGraph is active, use the following routing for every lookup:

| Task | Tool |
|---|---|
| Find symbol X | `codegraph_search` with the symbol name |
| Where is X called? | `codegraph_callers` |
| What does X call? | `codegraph_callees` |
| What breaks if I change X? | `codegraph_impact` at depth 2 |
| Get source of X | `codegraph_node` |
| What files exist? | `codegraph_files` |
| Summarize this codebase | `codegraph_context` — **SUBAGENT ONLY** — never call from main session |
| List packages indexed | `codegraph_status` |

Exceptions — still use Read for:
- Configuration files (`.env`, YAML/TOML config, Docker files)
- Build manifests (`package.json`, `Cargo.toml`, `go.mod`)
- READMEs and documentation files

### Step 3 — Audit entries

Every stage that runs with CodeGraph active MUST emit at least one `[CodeGraph]`
audit entry per stage. Minimum format:

```
[CodeGraph] active — queries: <N>, file_reads_avoided: <N>
```

For reverse-engineer, also emit per-artifact:
```
[CodeGraph] architecture.md — codegraph_context call replaced ~<N> file reads
```

### Step 4 — Blast-radius gate (code-generator only)

When generating or modifying code, after `codegraph_impact`:
- Log: `[Impact] <symbol> → <callers_count> callers, <callees_count> callees`
- If `callers_count > 20`: set `status: needs_human` with reason
  `"high-blast-radius edit: <symbol> has <N> callers — needs human approval before proceeding"`

## Verification

- `audit_entries[]` contains at least one `[CodeGraph]` entry per stage when
  `.codegraph/codegraph.db` is present.
- `codegraph_context` is NEVER called from the orchestrator's main session —
  only from spawned stage subagents.
- When CodeGraph is absent, the stage completes normally (graceful degradation).

## Common Rationalizations (reject these)

| Rationalization | Correct response |
|---|---|
| "grep is faster for this one lookup" | Use codegraph_search — it is always faster when indexed |
| "I'll just read the file, it's only one" | codegraph_node returns the same content in one deterministic call |
| "codegraph_context might saturate the main session" | Correct — ONLY call it from a spawned subagent |
| "the index might be stale" | Log `[CodeGraph] sync recommended` and still use it — WAL mode allows concurrent reads |
| "I don't know if it's indexed" | Always check Step 1 first |

## Red Flags

- Calling `codegraph_context` from the orchestrator's main session → escalate to `needs_human`.
- Using `Glob` or `find` for symbol lookup when CodeGraph is active → log as `[Rationalization-rejected]`.
- Index appears stale (file watcher died, recent `git checkout`): log `[CodeGraph] index may be stale — run codegraph sync`.
