# Executor Conformance Specification — v1

**Status:** DRAFT — adopted as the reference contract for tool-agnostic
executor adapters. First concrete adopter: ClaudeCodeExecutor (current
behaviour). Phase 5 adds OpenCodeExecutor.

**Audience:** anyone writing an AIDLC adapter for an agentic coding tool
other than Claude Code.

---

## 1. Purpose

The AIDLC orchestrator's differentiating features (parallel codegen, reviewer
fan-out, conflict detection, kill-and-resume) currently rely on Claude Code's
`Task()` spawn primitive. This spec defines the contract a runtime must
satisfy so the same orchestration logic can run unchanged on any agentic tool
that meets the contract.

A conforming executor is **transparent to the orchestrator**: the orchestrator
spawns stages, validates handoffs, and emits audit blocks identically
regardless of which executor backs the spawn.

---

## 2. Vocabulary

| Term | Meaning |
|---|---|
| **Stage agent** | A specialized agent for one AIDLC stage (`requirements-analyst`, `code-generator`, etc.). Defined at `.claude/agents/stage/<name>.md`. |
| **Input handoff** | A YAML document validated against `<stage>.input.v1.json` containing context_pointers, skill_paths, depth, etc. |
| **Output handoff** | A YAML document validated against `<stage>.output.v1.json` produced by the stage agent and committed to `<run-dir>/handoffs/`. |
| **Spawn** | A single execution of a stage agent against an input handoff that produces an output handoff. |
| **Run directory** | `.aidlc-orchestrator/runs/<run-id>/` — the per-run state directory holding manifest, handoffs, locks, timeline. |

---

## 3. Required interface

A conforming executor MUST implement an operation with the following
semantics, regardless of language or transport:

```
spawn(
    stage_name: str,
    input_handoff_path: pathlib.Path,
    *,
    timeout_sec: int | None = None,
    isolation: "worktree" | None = None,
) -> SpawnResult
```

### Inputs
- `stage_name`: the basename of the stage agent file (e.g. `"requirements-analyst"`).
- `input_handoff_path`: absolute path to a YAML handoff that validates against `<stage>.input.v1.json`.
- `timeout_sec`: optional wall-clock cap. Executors MUST respect this. On timeout, the executor MUST return a `SpawnResult` with `status: timeout`, NOT raise.
- `isolation`: optional. `"worktree"` requests an isolated git worktree for write isolation (used by parallel codegen). Executors that cannot satisfy this MUST refuse the spawn with `status: unsupported`.

### Output — `SpawnResult`
```yaml
status: "complete" | "blocked" | "failed" | "needs_human" | "timeout" | "unsupported"
output_handoff_path: <absolute path to validated output YAML>
tokens_in: <int>
tokens_out: <int>
wall_clock_sec: <float>
worktree_path: <optional path if isolation=worktree was honored>
error: <optional string if status in {failed, unsupported}>
```

### Invariants
1. The executor MUST validate the output handoff against `<stage>.output.v1.json` before returning. A schema-invalid output MUST yield `status: failed`.
2. The executor MUST NOT mutate `<run-dir>/manifest.yaml` or `<run-dir>/timeline.jsonl`. Those are orchestrator-owned.
3. The executor MUST append every spawn to `<run-dir>/handoffs/` with the canonical filename `<stage>.output.yaml` (or `<stage>.output.pass2.yaml` for two-pass stages).
4. The executor MUST surface cost data — `tokens_in`, `tokens_out`, `wall_clock_sec` — even on failure (best-effort when possible; zero is allowed when unknown).

---

## 4. Concurrency

Executors MUST support at least `N=4` concurrent in-flight `spawn()` calls.
Below that, layer-parallel codegen degrades to sequential and the AIDLC
orchestrator's parallelism guarantees are broken.

Adapters that cannot meet `N≥4` MUST:
- Declare `max_concurrency` in their registration metadata.
- Cause `/factory-build` to fall back to sequential mode and emit
  `[Executor] DEGRADED: concurrency cap <N>` in audit.

---

## 5. Cancellation

Executors MUST support cooperative cancellation:

```
cancel(spawn_id: str) -> CancelResult
```

After `cancel()`:
- The corresponding `spawn()` MUST return within `timeout_sec / 4` (or 30s if no timeout was set) with `status: cancelled`.
- Any partially-written output MUST be moved to `<run-dir>/handoffs/<stage>.output.cancelled-<ts>.yaml` (not the canonical filename, to avoid downstream consumption).

Adapters that cannot satisfy cancellation MUST advertise it and the
orchestrator will refuse to enter mid-flight cancellation flows — replays
become the only recovery primitive.

---

## 6. Audit emission

Executors MUST emit the following audit block at the END of each spawn (the
orchestrator appends it to `aidlc-docs/audit.md`):

```markdown
## <ISO8601> <PHASE> - <STAGE> COMPLETE
- [Executor] adapter: <executor-name> version: <version>
- [Executor] tokens_in: <N>, tokens_out: <N>, wall_clock_sec: <F>
- [Executor] worktree: <path|none>
- [Executor] cancelled: <true|false>
```

The orchestrator's existing audit-block helper (`factory_run.py emit_audit_block`)
handles atomic append, dedupe, and flock. Adapters only need to produce the
content rows; the orchestrator handles the file write.

---

## 7. Skill resolution

Executors MUST NOT load skill `SKILL.md` content into orchestrator-side
context (see `aidlc-docs/refactor/skills-audit.md`). The orchestrator stores
only resolved file paths in the manifest. Skill content is loaded by the
stage agent *inside its own isolated context*.

The executor's responsibility is to ensure the stage agent's isolated context
has filesystem access to the resolved paths.

For Claude Code: `.agents/skills/`, `~/.agents/skills/` — accessible because
the spawn runs in the same filesystem.
For OpenCode / others: the adapter MUST set up the same filesystem visibility
or fail-fast with `status: unsupported`.

---

## 8. Two-pass stage handling

Two-pass stages (currently only `requirements-analyst`) need special
treatment:

- Pass 1: input handoff has no `predecessor_artifacts` matching `*answered*`. Stage emits `status: needs_human` with `questions_artifact_path`. Executor MUST surface this to the orchestrator as `status: needs_human` — NOT as `failed`.
- Pass 2: input handoff includes the answered questions file. Stage emits `status: complete`. Executor writes output as `<stage>.output.pass2.yaml`.

The orchestrator distinguishes pass1/pass2 via the input handoff content; the
executor does not need state for this — it is stateless per spawn.

---

## 9. Worktree isolation (Claude-Code-specific behaviour)

When `isolation="worktree"`, the executor MUST:

1. Create a temporary worktree of the current branch via `git worktree add`.
2. Run the spawn against that worktree as CWD.
3. If the spawn produces ZERO changes, remove the worktree silently.
4. If the spawn produces changes, leave the worktree intact and return
   its absolute path in `worktree_path`.

The orchestrator owns merge / cleanup of populated worktrees.

Adapters that cannot satisfy git-worktree semantics MUST return
`status: unsupported` for worktree spawns. Phase 5's OpenCode adapter is
expected to support worktrees (OpenCode runs against a filesystem too).

---

## 10. Conformance tests

A conformance test suite lives at `tests/test_executor_conformance.py`
(Phase 5 deliverable 5.4). Each registered executor MUST pass the suite
unmodified.

The suite exercises:

| Test | What it verifies |
|---|---|
| `test_spawn_emits_valid_output` | output_handoff validates against schema |
| `test_spawn_emits_cost_data` | tokens_in/out and wall_clock_sec are non-null |
| `test_spawn_two_pass_round_trip` | requirements-analyst Pass 1 → human → Pass 2 |
| `test_concurrent_spawns_succeed` | N=4 concurrent spawns all return cleanly |
| `test_timeout_respected` | spawn with timeout_sec=1 returns `timeout` within 2s |
| `test_cancel_works` | spawn cancelled mid-flight returns `cancelled` |
| `test_worktree_isolation` | parallel writes to overlapping globs don't conflict when isolated |
| `test_failed_output_validation_yields_failed` | invalid output → status:failed |
| `test_unsupported_isolation_declared_upfront` | adapters that can't isolate say so |

---

## 11. Registration

Adapters register via `aidlc-scripts/executors/registry.yaml`:

```yaml
executors:
  - name: claude-code
    version: "0.2.0"
    module: aidlc-scripts.executors.claude_code_executor
    class: ClaudeCodeExecutor
    capabilities:
      max_concurrency: 8
      worktree_isolation: true
      cancellation: true
    target_tools: ["claude", "claude-code"]

  - name: opencode
    version: "0.1.0"
    module: aidlc-scripts.executors.opencode_executor
    class: OpenCodeExecutor
    capabilities:
      max_concurrency: 4
      worktree_isolation: true
      cancellation: true
    target_tools: ["opencode"]
```

The installer (`install_aidlc.py`) reads the registry to pick the right
executor per `--tool` value. Multi-tool installs (`--tool claude,opencode`)
register both — runtime picks by environment detection.

---

## 12. Migration from current Claude-Code-only design

Phase 5 lands this contract by:

1. **5.1 (this document)** — write the spec.
2. **5.2** — extract current Claude-Code spawn behaviour from inline
   orchestrator prose into `aidlc-scripts/executors/claude_code_executor.py`
   as the reference implementation. Run the conformance suite against it;
   suite passes are the regression bar.
3. **5.3** — write `opencode_executor.py` (and optionally `cursor_executor.py`).
   Pass the same suite.
4. **5.4** — wire `install_aidlc.py` to use the registry. Update the
   workflow doc pointer block per tool.

No orchestrator `.md` changes are required if the executors honour the
contract — the orchestrator's `Task(subagent_type=..., prompt=...)` call
remains the same; the executor wraps the underlying spawn mechanism.

---

## 13. Open questions (resolved during Phase 5 implementation)

- Should the `spawn_id` be allocated by the orchestrator (passed in) or by
  the executor (returned)? **Tentative answer:** allocated by the orchestrator
  via the run manifest — keeps cancellation deterministic.
- How are streaming token counts surfaced for cost-governor downshifting?
  **Tentative answer:** v1 is batch-only — final counts at spawn completion.
  Streaming is a v2 extension.
- Multi-tenant orchestrator running spawns on different tools? **Tentative
  answer:** out of scope for v1. One run, one executor.

---

## 14. Versioning

This is `executor.v1`. Backward-incompatible changes (signature changes,
new required fields, behavioural reinterpretation) MUST bump to v2 with a
new spec file. Adapters declare which version they implement; orchestrator
refuses to register an adapter whose version it does not support.

---

*End of spec. Implementing party: see Phase 5 plan in `TIER-GOD-PLAN.md`.*
