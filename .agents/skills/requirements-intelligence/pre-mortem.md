# Pre-Mortem

Fires at `comprehensive` depth when `stakes == prod` AND `risk ∈ {medium, high}`.
Also used standalone in the **plan-stage variant** (invoked by `workflow-planner`).

## Principle

Imagine this ships and fails publicly in 90 days. What broke? The pre-mortem
inverts optimism into structured risk discovery. Each predicted failure becomes
a question that either confirms a guardrail or surfaces a missing requirement.

## Failure categories (generate ≥3 questions covering these)

### Functional failure
*"The feature shipped, but users hated it."*
- Misread user intent
- Edge cases not covered
- Wrong success metric chosen

### Operational failure
*"The feature works in dev but broke in prod."*
- Performance under real traffic
- Cost explosion (compute, storage, third-party API spend)
- Security incident / data leak
- Reliability under failure (dependency outages, network partitions)

### Strategic failure
*"The feature works fine but it didn't matter."*
- Wrong audience — nobody adopted it
- Wrong timing — competitor shipped first
- Better alternative existed (build-vs-buy was wrong)

## Generation rubric

Question 1 — the top failure mode (MCQ across categories):

```
## Question
If this feature fails in production within 90 days of launch, the most likely cause is:

A) Performance — we didn't test at real-world scale
B) Edge case — an input we did not enumerate
C) Integration — a dependency we don't control
D) Adoption — users won't actually use it
E) Security / privacy — we missed a threat
F) Cost — running costs exceed our budget
G) Other (please describe after [Answer]: tag below)

[Answer]:
```

Question 2 — the guardrail for the top failure (always pair with Q1):

```
## Question
To prevent the failure you picked above, what guardrail must be in the requirements?

A) Explicit acceptance criterion + test scenario
B) Performance SLO / load test before launch
C) Monitoring / alerting / dashboards
D) Opt-out or kill switch
E) Manual approval gate before broad rollout
F) Other (please describe after [Answer]: tag below)

[Answer]:
```

Question 3 — adoption-specific (always include at comprehensive depth):

```
## Question
What evidence would convince you 30 days post-launch that this was the wrong thing to build?

A) Adoption below <threshold>
B) High abandonment / churn after first use
C) Support load spikes
D) No measurable impact on the metric we cared about
E) Other (please describe after [Answer]: tag below)

[Answer]:
```

## Stop conditions

- 3 quality failure-mode questions generated — stop.
- User already specified failure tolerances in the request (e.g. "this is a one-day prototype, crashes are OK") — emit one acknowledgement question, skip the rest.
- Coverage map already full — pre-mortem must not push you over budget.

## Red flag — hard escalation

If a pre-mortem question surfaces a failure mode the stated requirements
**cannot prevent**, escalate:

`[RedFlag] requirements-intelligence: pre-mortem surfaced unaddressed risk: <description>. Stated requirements do not prevent it.`

Examples:
- User says "data loss not acceptable" + request has "no database, no persistence".
- User says "must scale to 1M users" + request specifies "single-process, in-memory".
- User says "must be GDPR compliant" + no consent / deletion / export mechanism specified.

In these cases set `status: needs_human` and present the conflict for resolution
before allowing requirements.md to be written.

## Plan-stage variant

When invoked by `workflow-planner`:

- Operate on the *plan artifact* (the Mermaid diagram + unit list + task tree),
  not the original request.
- Ask:
  1. "If this plan fails during construction, where will it break first?"
     (options: integration boundaries, layer-3 dependency tasks, the longest task, a unit with no tests, other)
  2. "Which unit boundary, if wrong, will force a re-plan?"
     (options: <unit-name-1>, <unit-name-2>, ... | none)
  3. "Which task has the weakest acceptance criterion?"
     (options: enumerate the lowest-AC-quality tasks | all are clear | other)
- Output: ≤3 questions appended to plan approval surface (NOT a separate questions file).

## Output for SKILL.md Step 6

Each generated question tagged to coverage axis `Risks` (or `Acceptance` for Q2 — the guardrail question).
