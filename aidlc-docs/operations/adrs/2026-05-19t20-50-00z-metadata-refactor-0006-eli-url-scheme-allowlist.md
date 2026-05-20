# ADR 0006: ELI URL Scheme Allowlist in `derive_eli`

**Run:** 2026-05-19t20-50-00z-metadata-refactor
**Date:** 2026-05-19
**Status:** Accepted

## Context

ELI (European Legislation Identifier) values are extracted from document frontmatter
and stored in `metadata_['eli']`. The `/analyze` endpoint returns `eli` in the `fuentes`
payload, which the Angular frontend binds directly to an `[href]` attribute to render a
clickable link to the official legal text.

A security review (CWE-601, A03:2021) identified that any string from frontmatter is
accepted as a valid ELI value without scheme validation. A corpus document can store a
`javascript:`, `data:`, or `vbscript:` URI in its `eli` frontmatter key. This value
would be:
1. Persisted to `metadata_['eli']` in the database.
2. Returned verbatim by the API.
3. Rendered as `href` in the Angular template, potentially executing script in the
   browser if Angular's sanitisation is bypassed or if server-side rendering is added.

Angular's `[href]` binding sanitises `javascript:` URIs in most cases, but:
- The sanitisation is Angular-version-dependent and not guaranteed across upgrades.
- SSR (Angular Universal) removes the DOM sanitisation layer.
- The correct defence is server-side, at the point where the value enters the system.

Two mitigations were considered:

1. **Frontend-only sanitisation via `DomSanitizer`**: applied at render time. Does not
   prevent the malicious value from being stored in the database or returned by the API
   to other potential consumers.
2. **Server-side allowlist in `derive_eli` + API serialiser**: the value is rejected at
   ingestion time (in `metadata_helpers.py`) and at API boundary (in `main.py`). This
   is defence-in-depth: neither storage nor transmission of an invalid URI is permitted.

## Decision

Add an allowlist scheme check at two enforcement points:

1. **`derive_eli` in `metadata_helpers.py`**: before returning an ELI value, verify
   that it starts with `https://`, `http://`, or the relative prefix `eli/` (used by
   the Spanish BOE for relative ELI paths). Any other value (including empty strings
   that match a disallowed scheme) returns `None`.

2. **API serialiser in `main.py`**: in the `fuentes` list comprehension, validate each
   `eli` value against the same allowlist before including it in the response. An
   invalid value is replaced with an empty string so that the frontend receives a
   consistent shape.

The two enforcement points are intentionally redundant: `derive_eli` prevents storage
of invalid URIs, and the API serialiser provides a safety net in case a legacy document
already in the database carries a pre-migration value.

## Consequences

**Positive:**
- Eliminates the `javascript:` / `data:` URI injection path at both storage and
  transmission boundaries.
- Defence-in-depth: two independent enforcement points.
- Simple allowlist with three entries — easy to audit, easy to extend if the BOE
  changes its ELI URI format.
- No impact on legitimate ELI values (all observed BOE ELI identifiers use `https://`
  or relative `eli/` paths).

**Negative / Trade-offs:**
- If a new ELI URI scheme is introduced (e.g., a URI-based identifier for another EU
  member state), the allowlist must be updated. The constant is defined in
  `metadata_helpers.py` as `_ELI_ALLOWED_PREFIXES` with a comment.
- Relative `eli/` paths are not absolute URLs. The frontend must handle the relative
  path case (prepend the base URL of the legal corpus) or use absolute URLs only.

**References:** CWE-601, A03:2021, OWASP A03:2021 Injection, Angular Security Guide
