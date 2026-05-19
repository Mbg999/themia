# Questioning Policy — Routing Matrix

Authoritative routing rules that decide which elicitation techniques fire on a
given request. Referenced by `SKILL.md` Step 3.

## Inputs to the router

| Input | Source | Domain |
|---|---|---|
| `depth` | Step 3 of `requirements-analysis.md` (after honoring `depth_override`) | minimal / standard / comprehensive |
| `clarity` | Step 2 classification | Clear / Vague / Incomplete |
| `risk` | derived: reversibility × blast radius | low / medium / high |
| `novelty` | derived: greenfield → high, brownfield reuse → low | low / medium / high |
| `stakes` | derived from request: "prototype" / "internal" / "production" / "MVP" → maps to enum | prototype / internal / prod |
| `ambiguity_count` | `ambiguity-detection.md` lexicon scan | integer |

## Derivation rules

- `risk = high` when scope is `System-wide` or `Cross-system`, or when the request mentions migration / data backfill / breaking change.
- `risk = medium` when scope is `Multiple Components` or the request touches auth / billing / data integrity.
- `risk = low` for all other cases.
- `novelty = high` when greenfield OR brownfield + unfamiliar stack referenced in the request.
- `stakes = prod` when the request uses "production", "customers", "users will see", "launch", or a deployment target is specified.
- `stakes = prototype` when the request uses "PoC", "prototype", "demo", "experiment", "playing with".
- `stakes = internal` otherwise.

## Routing matrix

| Technique | Always at | Triggered when (overrides depth) |
|---|---|---|
| `coverage-map` | all depths | always — axis set varies by depth |
| `ambiguity-detection` | standard, comprehensive | `ambiguity_count ≥ 3` (forces it on at minimal) |
| `socratic` | comprehensive | `clarity == Vague` at any depth |
| `assumption-mining` | comprehensive | `novelty == high` at any depth |
| `pre-mortem` | comprehensive | `stakes == prod` AND `risk ∈ {medium, high}` |

## Question budget by depth

| Depth | Min questions | Max questions | Drop priority (when above max) |
|---|---|---|---|
| minimal | 3 | 5 | Unknowns → Context → Limits → Risks → Expectations → Acceptance → Needs → Purpose |
| standard | 5 | 10 | same |
| comprehensive | 8 | 18 | same |

Drop priority is read left-to-right: Unknowns drops first, Purpose never drops.

## Below-min recovery

If after dedupe the question count is below the depth's min:

1. Re-run any triggered technique that produced zero candidates.
2. If still below min, escalate the active depth one level (minimal→standard, standard→comprehensive). Log the escalation: `[DepthEscalation] from <old> to <new>: insufficient coverage`.
3. If at comprehensive and still below min, set `status: needs_human` with `[RedFlag] requirements-intelligence: cannot reach minimum coverage at comprehensive depth — request likely too underspecified for MCQ format`.

## Special cases

### Trivial + Clear + Single File
- `request_classification.complexity == Trivial` AND `clarity == Clear` AND `scope == Single File`.
- The existing rule (`requirements-analyst.md` line 138) allows skipping the questions phase.
- Even when skipped, this skill MUST still emit `audit_entries[]` proving:
  - Rule file was read (`[SkillRead]`)
  - Signal scoring was done (`[SignalScore]`)
  - Coverage map was evaluated and all axes mapped to evidence from the request itself (`[CoverageMap]` with status `inferred-from-request`)
- The `[QuestionBudget]` entry shows `0/<max> — Trivial+Clear+SingleFile skip path`.

### Brownfield with reverse-engineering present
- Skip Context axis questions that workspace-scout / reverse-engineer already answered.
- Quote the RE artifact as the answer: `[CoverageMap] Context: covered by reverse-engineering/technology-stack.md L<n>`.

### User typed answers in chat, not in the file
- Do NOT proceed.
- Re-prompt with the missing-answer template from `question-format-guide.md`.
- Log `[Compliance] question-format-guide.md: re-prompt sent because user answered in chat`.

### `depth_override` present in input
- The stage agent honors it (line 67-68 of `requirements-analyst.md`).
- This skill reads the final depth — no special handling needed.

## Plan-stage variant

When invoked by `workflow-planner`:

- Only `pre-mortem` triggers, regardless of signal scores.
- `pre-mortem` operates on the *plan artifact*, not the original user request.
- Question cap: 3.
- Output appended to plan approval — not a separate questions file.
