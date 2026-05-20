# ADR 0005: 64 KB YAML Frontmatter Size Gate in `parse_frontmatter`

**Run:** 2026-05-19t20-50-00z-metadata-refactor
**Date:** 2026-05-19
**Status:** Accepted

## Context

The ingestion pipeline calls `yaml.safe_load` on the YAML frontmatter block extracted
from each Markdown document in the corpus. `yaml.safe_load` protects against arbitrary
code execution (it does not allow custom Python constructors), but it does not protect
against YAML alias-based denial-of-service attacks — the "billion laughs" pattern, where
deeply nested anchors and aliases cause exponential memory/CPU expansion.

Although the corpus is currently a pinned, trusted repository of Spanish legal documents,
the security review (CWE-400, A05:2021) identified two risk paths:

1. A future commit to the upstream repository (the pin could be updated by any team
   member) could introduce a malicious frontmatter block.
2. If the ingestion pipeline is ever extended to accept uploads from external parties,
   the untrusted-input surface becomes immediate.

Three mitigations were evaluated:

1. **Subprocess isolation with memory limits**: runs `yaml.safe_load` in a child process
   with `ulimit -v`. Provides the strongest isolation but adds significant complexity
   (subprocess management, serialisation, error propagation) for a CLI ingestion script.
2. **Wall-clock timeout via `signal.alarm`**: limits CPU time per parse call. Requires
   UNIX signal support (not portable to Windows), and `signal.alarm` cannot be used
   inside threads.
3. **Byte-length gate before parsing**: reject any frontmatter block exceeding a fixed
   byte threshold before calling `yaml.safe_load`. Simple, portable, zero-overhead for
   legitimate documents, and eliminates the attack surface entirely for size-bounded
   inputs.

## Decision

Enforce a 64 KB maximum byte length on the raw YAML frontmatter block inside
`parse_frontmatter` before calling `yaml.safe_load`. If the extracted block exceeds
64 KB, `parse_frontmatter` raises a `ValueError` with a descriptive message and the
document is skipped with a warning log entry.

The threshold of 64 KB was chosen because:
- The largest legitimate Spanish legal frontmatter block observed in the corpus is
  approximately 800 bytes.
- 64 KB provides a factor-of-80 safety margin above observed legitimate sizes.
- A 64 KB YAML block cannot produce more than approximately 64 KB of parsed output
  when aliases are bounded to the input size — the expansion ratio for safe YAML is 1:1.

## Consequences

**Positive:**
- Eliminates the YAML billion-laughs attack surface for inputs below the threshold.
- Zero performance impact on legitimate documents (a byte-length check is O(1) via
  `len()`).
- Portable — does not depend on UNIX signals or subprocess management.
- Simple to audit: one guard, one threshold constant, one log line.

**Negative / Trade-offs:**
- Does not protect against a YAML bomb injected into a block smaller than 64 KB
  (though such a bomb would have limited expansion ratio).
- The threshold is a magic number. It is defined as a module-level constant
  `_MAX_FRONTMATTER_BYTES = 65_536` in `metadata_helpers.py` with a comment
  explaining the rationale.

**Deferred:**
- If the ingestion pipeline is extended to accept untrusted uploads, subprocess
  isolation should be revisited as an additional layer.

**References:** CWE-400, A05:2021, PyYAML safe_load documentation
