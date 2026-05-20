# ADR 0002: SSRF Protection via Ollama Host Validation

**Run:** 2026-05-20t08-41-48z-bge-m3-migration
**Date:** 2026-05-20
**Status:** Accepted

## Context

The Ollama embedding backend introduced in ADR 0001 of this run accepts a caller-supplied
`OLLAMA_HOST` environment variable that is passed directly to `ollama.Client(host=...)`.
If that variable is set to an attacker-controlled value — or if an operator accidentally
sets it to a plain `http://` internal address — the application becomes an SSRF
(Server-Side Request Forgery) vector (CWE-918).

Concrete attack paths identified during the security review:

1. **Deployment misconfiguration**: an operator sets `OLLAMA_HOST=http://169.254.169.254`
   (AWS metadata endpoint) or another internal address. Every embed call would silently
   exfiltrate data to that host.
2. **Environment variable injection**: in some container orchestration environments, an
   attacker with partial control over the pod spec could inject `OLLAMA_HOST` to redirect
   embedding traffic.
3. **`ingest.py` as CLI SSRF vector**: the ingestion script reads the same `OLLAMA_HOST`
   env var. A developer running the script in a CI/CD environment with tainted environment
   variables would be vulnerable.

The review also flagged that exception handlers in the original implementation logged the
full Ollama URL, which would expose internal hostnames in log aggregators.

## Decision

Introduce a `_validate_host(host: str) -> None` function in `embedder.py` that enforces:

1. **Scheme requirement**: the host string must start with `https://` or be a localhost
   address (`http://localhost`, `http://127.0.0.1`). All other schemes — including plain
   `http://` to non-localhost addresses — raise `ValueError` at startup.
2. **Fail-fast at startup**: `_validate_host()` is called in the FastAPI lifespan
   context manager (`app/main.py`) so the server refuses to start with an invalid host
   rather than failing on the first embed request.
3. **Called in the singleton constructor**: `EmbedderClient.__init__` calls
   `_validate_host()` before constructing `ollama.Client`, so the same protection applies
   to any programmatic instantiation outside the web server.
4. **Applied to `ingest.py`**: the ingestion CLI calls the same validation function
   before creating its Ollama client, closing the CLI SSRF path.
5. **Exception logging sanitised**: caught exceptions in the embedder log the error
   message only, not the full URL, preventing host/path leakage.

Localhost `http://` is explicitly allowed because local development environments commonly
run Ollama without TLS. The allow-list is not configurable at runtime; it is a hard-coded
security invariant.

## Consequences

**Positive:**
- Eliminates the SSRF risk introduced by a configurable HTTP endpoint. An operator
  cannot accidentally (or a malicious env-var injection cannot deliberately) point the
  embedder at an internal HTTP service.
- Fail-fast startup prevents the server from operating in a misconfigured state, making
  deployment problems visible immediately rather than at query time.
- The same validation function is used in both `embedder.py` and `ingest.py`, so the
  security invariant cannot drift between the two code paths.
- No performance impact: validation runs once at startup, not on every embed call.

**Negative / Trade-offs:**
- Operators who run a private Ollama instance over plain `http://` on a non-localhost
  address (e.g., in a trusted internal network) must either add TLS to Ollama or use an
  SSH port-forward to `localhost`. This is an intentional friction point, not a bug.
- If `OLLAMA_HOST` is unset, the embedder defaults to `http://localhost:11434` (Ollama's
  default). This passes validation but will fail at runtime if no local Ollama instance
  is running. The error message directs operators to set `OLLAMA_HOST`.

**Risks:**
- The localhost allowlist (`http://localhost`, `http://127.0.0.1`) does not cover IPv6
  loopback (`http://[::1]`). A future hardening pass should add `http://[::1]` to the
  allowlist if IPv6-only environments are supported.
- The validation does not perform DNS resolution or check for SSRF via DNS rebinding.
  A sophisticated attacker who controls DNS could still redirect a validated
  `https://ollama.cvbooster.es` hostname. This is considered out of scope for the current
  threat model; mTLS or network-level controls would be required to close this gap.
