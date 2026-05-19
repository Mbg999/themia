# CodeGraph — Token Savings Baseline

> Record baseline measurements here to validate the Phase 3 (reverse-engineer)
> and Phase 5 (build-test-agent) integration against the success criteria in
> CODEGRAPH-INTEGRATION-PLAN.md §6.

## How to measure

Run the same pipeline against a brownfield repo **with** and **without**
`.codegraph/`. Use the factory telemetry output from `/factory-state` after
each run.

```bash
# Without CodeGraph (move index aside)
mv .codegraph .codegraph.bak
/factory-spec "characterize this codebase"
# Record metrics below, then restore
mv .codegraph.bak .codegraph

# With CodeGraph
/factory-spec "characterize this codebase"
# Record metrics below
```

## Metrics to capture per run

| Metric | Without CodeGraph | With CodeGraph | Reduction |
|---|---|---|---|
| reverse-engineer tool calls | | | |
| reverse-engineer tokens in | | | |
| reverse-engineer wall clock (min) | | | |
| build-test-agent tests run | | | |
| build-test-agent wall clock (min) | | | |
| reviewer pool tool calls (total) | | | |

## Success criteria (CODEGRAPH-INTEGRATION-PLAN.md §6)

- Token reduction ≥ 70% on brownfield reverse-engineer
- Tool-call reduction ≥ 80% in reviewer pool on a multi-file PR
- Test runtime reduction ≥ 50% on a single-unit edit via `codegraph affected`
- Zero regressions in stages without CodeGraph

## Baseline runs

<!-- Fill in as measurements are taken -->

### Run 1

- Date: _
- Repo: _
- Without CodeGraph: tool calls=_, tokens_in=_, wall_clock=_min
- With CodeGraph: tool calls=_, tokens_in=_, wall_clock=_min
- Notes: _
