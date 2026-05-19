# Assumption Mining

Fires when `novelty == high` (greenfield, unfamiliar domain) at comprehensive
depth, or any time the request is short relative to the scope it implies.

## Principle

Every short request hides many assumptions. Surfacing them lets the user confirm
or reject — which is often faster than generating one question per axis.
Assumption mining is high-leverage when the user gave you a single sentence and
expects a multi-week build.

## Process

1. Re-read the user's request verbatim.
2. Enumerate every assumption you (the agent) would have to make to start work.
   Categorize:
   - **Stack assumptions** — language, framework, version, OS, runtime
   - **Architecture assumptions** — deployment model, hosting, persistence, statefulness
   - **Behavior assumptions** — default workflows, error handling, retry policy, auth model, concurrency
   - **User assumptions** — who the user is, what device, what context
   - **Quality assumptions** — testing, observability, performance budget, security posture
3. Classify each assumption:
   - **stated** — explicit in the request
   - **implicit** — you would have to invent it
   - **unknown** — could go either way; needs an opinion
4. Convert each *implicit* and *unknown* assumption into a confirm-or-reject MCQ.

## Generation rubric

Unlike normal MCQs, assumption-mining questions are **additive** — the user can
flag multiple wrong assumptions at once. State this explicitly in the question:

```
## Question
The request implies these assumptions. Mark any that are WRONG.
(You may pick multiple letters — list them in [Answer]: e.g. "B, D")

A) The app must work offline as well as online
B) Authentication uses email + password (not SSO / OAuth)
C) Data persists across browser refresh
D) Multiple users chat simultaneously in the same room
E) Real-time message delivery is required (vs polling)
F) Desktop browser is the primary target (not mobile)
G) All of these assumptions are correct
H) Other (please describe after [Answer]: tag below)

[Answer]:
```

The instruction text — "You may pick multiple letters" — is mandatory in
assumption-mining questions and only here. Standard MCQ rules require
single-letter answers; this is the documented exception.

## Output to audit

Add to `audit_entries[]`:

```
[Assumptions] stated: <n>, implicit: <n>, unknown: <n>
[Assumptions] mined: ["<assumption 1>", "<assumption 2>", ...]
```

For each implicit / unknown assumption that became a question, log the link:
`[Assumptions] question <Q-id> covers assumption: "<text>"`.

## Stop conditions

- Cap implicit assumptions at 8 per request — beyond that, the request is too
  underspecified for MCQ format.
- Emit `[RedFlag] requirements-intelligence: >8 implicit assumptions — request
  needs conversational triage` and let SKILL.md handle the escalation.
- Stated assumptions never become questions (the user already told us).

## Worked example

### Request
> "Build a fast chat app, with angular and custom scss for front, use the
> ng new cli command, and node with express and socketio for backend, no database"

### Assumptions enumerated

**Stated**:
1. Frontend stack: Angular + custom SCSS
2. Backend stack: Node + Express + Socket.IO
3. Bootstrap: `ng new`
4. No persistent database

**Implicit** (each becomes a candidate question):
1. Single chat room vs multi-room
2. Users have no identity / anonymous vs require name on join
3. Message history only for active session (no persistence implied)
4. Single-server deployment (Socket.IO sticky sessions not addressed)
5. Browser-only (no mobile app)
6. English UI (no i18n)
7. No auth / open access
8. Local dev only vs deployed somewhere

**Unknown**:
1. How many concurrent users expected
2. Whether typing indicators / read receipts are in scope
3. Whether file / image messages are in scope

→ Generate 1 MCQ covering implicit 1-7 (additive), and 1 MCQ covering the
unknowns. Total: 2 assumption-mining questions, ~8 axis coverage hits.

## Coverage axis tagging

Assumption-mining questions tag to **multiple axes** simultaneously (this is
their power). When emitting to the coverage map, mark each axis touched:

```
[CoverageMap] Q<id>: Limits + Context + Expectations (assumption-mining)
```
