# Socratic Probing

Fires when `clarity == Vague` at any depth, or always at `comprehensive`. The
goal is to surface the **real** motivation behind a stated goal, which often
reframes the spec entirely.

## Principle

A user request is typically the L1 answer to an unasked question. Asking *why*
up to three levels deep surfaces:

- **L1** → what the user said they want
- **L2** → the immediate driver (why now)
- **L3** → the deeper motivation (the real goal)

The L3 answer is often what should actually drive the spec.

## The why-chain

For the top stated goal in the request:

1. **Why this, why now?** What changed that makes this worth building today?
2. **Why this approach?** Why not the obvious alternative (buy, integrate, do-nothing, defer)?
3. **Why this scope?** Why not bigger (full system) or smaller (one slice)?

Each level produces ONE MCQ in the questions file. Stop early if a prior answer
was already concrete and measurable — don't ask three "why"s mechanically.

## Generation rubric

Each why becomes an MCQ anchored against real alternatives — never abstract.

### L1 — Why now
```
## Question
What changed recently that makes this worth building now?

A) New user demand / complaints from existing users
B) An existing tool we use is being deprecated / changing pricing
C) Compliance / legal deadline
D) Strategic initiative or stakeholder mandate
E) Personal / learning project — no external driver
F) Other (please describe after [Answer]: tag below)

[Answer]:
```

### L2 — Why this approach
```
## Question
Why build this in-house vs an existing alternative?

A) Cost — existing tools are too expensive at our usage level
B) Control — we need customization beyond what tools allow
C) Integration — existing tools don't fit our stack / data model
D) Learning — this is partly an educational exercise
E) We evaluated alternatives and they don't exist for our need
F) Other (please describe after [Answer]: tag below)

[Answer]:
```

### L3 — Why this scope
```
## Question
Why this specific scope (vs bigger or smaller)?

A) Smallest thing that delivers user value (true MVP)
B) Largest thing we can ship before a deadline
C) Matches a previously approved spec / RFC
D) Scope is exploratory — we'll learn what to cut
E) Other (please describe after [Answer]: tag below)

[Answer]:
```

## Stop conditions

Stop probing if any of:

- L1 answer is already concrete and measurable (e.g., user pasted a JIRA ticket with all context).
- User explicitly says "just build it, I don't want to debate motivation" (in input or prior context).
- Three levels deep yielded no new information.
- Budget (from `questioning-policy.md`) is at the depth max.

## Common failure modes

| Failure | Fix |
|---|---|
| Why-chain becomes interrogation | Cap at 3 levels, always offer Other, never repeat a why on the same axis |
| Asking "why" abstractly | Anchor against real alternatives (buy / build / integrate / skip / defer) |
| Treating L1 as truth | When `clarity == Vague`, always go to L2 minimum |
| Re-asking what workspace-scout already answered | If RE artifact answers the L2, skip it and cite |

## Output

Add one candidate question per why-level that fires, tagged to coverage axis
`Purpose` (the why-chain primarily probes purpose; L3 may tag `Limits` if the
answer reveals scope boundaries).
