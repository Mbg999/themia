# Quality SLOs

Service Level Objectives for AIDLC orchestrator stages. Breaches trigger a
`[SLOBreach]` audit entry. When `features.slo_blocking` is enabled, the next
stage spawn is blocked until the breach is acknowledged in `slo-acks.md`.

Thresholds are intentionally loose at launch — tighten via PR as the system
matures and the historical baseline establishes itself.

```yaml
# Each SLO: stage, metric, comparator, threshold, severity.
# Comparator: `<` or `<=` for "must stay below"; `>` or `>=` for "must stay above".
# Severity: warn | block. `block` SLOs gate the next-stage spawn.
slos:
  # ---- requirements-analyst ----
  - stage: requirements-analyst
    metric: evidence_fail_rate
    comparator: "<"
    threshold: 0.05    # ≥5% of runs failing content validation is a regression
    severity: block

  - stage: requirements-analyst
    metric: needs_human_rate
    comparator: "<"
    threshold: 1.01    # informational only — always 1.0 by design (Pass 1)
    severity: warn

  - stage: requirements-analyst
    metric: redflag_rate
    comparator: "<"
    threshold: 0.20    # >20% red-flag rate suggests upstream request quality issues
    severity: warn

  # ---- workflow-planner ----
  - stage: workflow-planner
    metric: evidence_fail_rate
    comparator: "<"
    threshold: 0.05
    severity: block

  - stage: workflow-planner
    metric: blocked_rate
    comparator: "<"
    threshold: 0.10
    severity: warn

  # ---- code-generator ----
  - stage: code-generator
    metric: evidence_fail_rate
    comparator: "<"
    threshold: 0.05
    severity: block

  - stage: code-generator
    metric: failed_rate
    comparator: "<"
    threshold: 0.10
    severity: warn

  # ---- build-test-agent ----
  - stage: build-test-agent
    metric: evidence_fail_rate
    comparator: "<"
    threshold: 0.10  # build/test failures can have legit causes — looser
    severity: warn

  # ---- ship-agent ----
  - stage: ship-agent
    metric: evidence_fail_rate
    comparator: "<"
    threshold: 0.05
    severity: block

  # ---- universal ----
  - stage: "*"          # applies to every stage
    metric: redflag_rate
    comparator: "<"
    threshold: 0.30     # >30% red-flag rate across any stage is a system-level issue
    severity: warn
```

## How acknowledgement works

When a `block`-severity SLO breaches, the orchestrator refuses to spawn the
next stage until you add an entry to `aidlc-docs/quality/slo-acks.md`:

```yaml
# slo-acks.md — acknowledged SLO breaches
acks:
  - stage: requirements-analyst
    metric: evidence_fail_rate
    observed: 0.08
    threshold: 0.05
    acknowledged_at: 2026-05-15
    acknowledged_by: "<your name or handle>"
    rationale: "Two recent runs failed due to a known issue in axis-tag
                emission; fix landing in next sprint. Continuing in warn mode
                meanwhile."
    expires_at: 2026-06-01  # optional — re-blocks after this date
```

After the expires_at date, the breach re-blocks until re-acknowledged.

## How to use this file

- Manual review: read the SLO list to know what good looks like.
- Automated check: `python3 aidlc-scripts/factory_slo_check.py` reads this
  file + the most recent quality report and returns exit 1 on unacknowledged
  block breaches.
- CI: invoke the check script as part of `/factory-build` or `/factory-ship`
  preflight when `features.slo_blocking: true`.
