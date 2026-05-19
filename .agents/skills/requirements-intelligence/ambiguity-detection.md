# Ambiguity Detection

Scan the user's request text for terms that look meaningful but aren't. Each
ambiguous term either becomes a quantifier question or is logged as deliberately
fuzzy (with the user's blessing).

## Weasel-word lexicon

### Performance adjectives
`fast`, `slow`, `responsive`, `snappy`, `quick`, `real-time`, `low-latency`,
`high-throughput`, `instant`, `lag-free`

→ Quantifier MCQ:
```
## Question
The request used "<term>". What target counts as <term>?

A) <p50 / threshold A>
B) <p50 / threshold B>
C) <p99 / threshold C>
D) Not performance-critical
E) Other (please describe after [Answer]: tag below)

[Answer]:
```

### Scale adjectives
`scalable`, `large-scale`, `enterprise`, `production-grade`, `robust`,
`industrial`, `handles many users`, `high-volume`

→ Quantifier MCQ:
```
## Question
What scale must this support at launch?

A) <100 users / events per minute
B) 100 – 10k
C) 10k – 1M
D) >1M
E) Other (please describe after [Answer]: tag below)

[Answer]:
```

### Quality adjectives
`secure`, `reliable`, `clean`, `modern`, `simple`, `easy`, `nice`, `good UX`,
`professional`, `polished`, `production-ready`, `solid`

→ Each maps to a measurable. Pick the most relevant axis:
- `secure` → threat model question (which threats matter — auth, transport, data-at-rest, supply-chain)
- `reliable` → SLO question (uptime target, allowed error rate)
- `clean` → linter/style standard question
- `modern` → target framework/language version question
- `simple` / `easy` → primary user-action MCQ ("the most common action should take how many clicks?")

### Vague nouns
`stuff`, `things`, `etc.`, `and so on`, `users` (without qualifier), `data`
(without qualifier), `features`

→ Enumeration MCQ. Force the user to enumerate the actual set.

### Implicit comparatives
`better`, `improved`, `faster than before`, `cleaner`, `more efficient`

→ Anchor MCQ:
```
## Question
The request said "<comparative term>". Better than what baseline?

A) <existing system X>
B) <competitor Y>
C) General industry norm
D) No baseline — just "good enough"
E) Other (please describe after [Answer]: tag below)

[Answer]:
```

### Open-ended adverbs
`hopefully`, `ideally`, `maybe`, `possibly`, `if possible`, `nice to have`

→ Reclassify MCQ:
```
## Question
The request said "<term>" for <feature>. Is this a must-have or nice-to-have?

A) Must-have — blocks launch if missing
B) Nice-to-have — ship without it if needed
C) Future scope — not for this version
D) Other (please describe after [Answer]: tag below)

[Answer]:
```

## Process

1. Tokenize the user's request (full text + workspace-scout output if brownfield).
2. For each token / phrase matching the lexicon, increment `ambiguity_count` and add a candidate question tagged with the most relevant coverage axis (typically Expectations or Needs).
3. Compound phrases (e.g. `user-friendly`, `production-grade`) match by phrase rules.
4. Return the candidate list to SKILL.md Step 6 for merging and dedupe.

## Output shape

For SKILL.md Step 2:
```yaml
ambiguity_count: 4
candidate_questions:
  - term: "fast"
    axis_hint: Expectations
    mcq:
      stem: "What latency target counts as 'fast' for <feature>?"
      options: ["<100 ms", "<500 ms", "<1 s", "Not perf-critical", "Other"]
  - term: "scalable"
    axis_hint: Expectations
    mcq:
      stem: "What user / request scale must this support at launch?"
      options: ["<100", "100-10k", "10k-1M", ">1M", "Other"]
  ...
```

## Worked example

### Request
> "Build a fast chat app, scalable, with clean code, no database."

### Detected ambiguities
| Term | Axis | Reasoning |
|---|---|---|
| `fast` | Expectations | performance adjective with no quantifier |
| `scalable` | Expectations | scale adjective with no target |
| `clean code` | Context | quality adjective — needs lint/style standard |

`ambiguity_count = 3` → triggers ambiguity-detection even at minimal depth.

### NOT flagged
| Phrase | Why not |
|---|---|
| `chat app` | concrete enough at any depth |
| `no database` | explicit constraint, already a Limits answer |
| `angular` | named framework, no quantifier needed |
| `socketio` | named library, concrete |

## Stop conditions

- Cap candidates at 8 per request — beyond that the request is too vague for
  MCQ format. Emit `[RedFlag] requirements-intelligence: ambiguity_count > 8 —
  request needs conversational triage first` and let SKILL.md handle escalation.
