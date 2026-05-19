# Context Compaction (mandatory)

PRIORITY: P3

After every inline stage execution:
- extract structured outputs and artifacts
- discard raw chain-of-thought
- compact critical state into summaries

Raw chain-of-thought never carries forward. Compact reasoning summaries
(tradeoff rationale, constraints, rejected alternatives) MAY survive when
operationally necessary — but they MUST be explicit, not hidden accumulators.

See `index.md §0` principle 6.
