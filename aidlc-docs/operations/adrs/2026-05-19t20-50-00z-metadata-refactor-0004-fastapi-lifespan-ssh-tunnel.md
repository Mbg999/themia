# ADR 0004: FastAPI Lifespan for SSH Tunnel Lifecycle Management

**Run:** 2026-05-19t20-50-00z-metadata-refactor
**Date:** 2026-05-19
**Status:** Accepted

## Context

The Thermia backend connects to a remote PostgreSQL instance via an SSH tunnel (using
`sshtunnel.SSHTunnelForwarder`). In the MVP implementation, the tunnel was started
inside `get_engine()` and stopped in a `finally` block at the end of each `/analyze`
request handler.

A code review (correctness axis, P1) identified a critical bug: stopping the tunnel
after each request tears down the SSH connection, making every subsequent request fail
with a connection error until the next call to `get_engine()` — which restarts the
tunnel, burning connection setup latency on every request. Under concurrent load, two
requests racing to restart the tunnel can corrupt the tunnel state.

Two alternative lifecycle approaches were considered:

1. **Module-level singleton with `atexit` teardown**: simpler, but does not integrate
   with ASGI lifecycle events and can leave the tunnel open if the process is killed
   with SIGKILL or during hot-reload cycles.
2. **FastAPI `lifespan` context manager (`@asynccontextmanager`)**: the recommended
   FastAPI pattern for managing resources that must be created once at startup and torn
   down at shutdown. Integrates cleanly with uvicorn's ASGI lifecycle, is testable via
   `TestClient(app)` context manager, and is compatible with graceful shutdown signals.

## Decision

Move the SSH tunnel and SQLAlchemy engine lifecycle to a FastAPI `lifespan` context
manager. The lifespan function:

1. Calls `get_engine()` once at application startup, storing the engine (and tunnel, if
   in local mode) in application state.
2. Yields control to the application.
3. Stops the tunnel (if present) at application shutdown, after the last request has
   been served.

The `get_engine()` function returns a `(engine, tunnel_or_None)` pair explicitly rather
than attaching a `.tunnel` attribute to the engine object. This removes the `hasattr`
guard and makes the tunnel's optional presence explicit in the type signature.

The `analyze` request handler reads the engine from `request.app.state` rather than
calling `get_engine()` directly.

## Consequences

**Positive:**
- The SSH tunnel is created once and reused for the entire application lifetime,
  eliminating per-request connection overhead and the teardown bug.
- `asyncio.to_thread()` replaces `asyncio.get_event_loop().run_in_executor()` in the
  handler, making the code Python 3.10+ compatible and idiomatic.
- The tunnel teardown is guaranteed by the ASGI lifespan protocol, including during
  graceful shutdown initiated by Kubernetes or `uvicorn --reload`.
- The `(engine, tunnel)` return type makes the tunnel's presence explicit and removes
  the need for defensive `hasattr` guards.

**Negative / Trade-offs:**
- Lifespan-scoped state is less visible than module-level singletons; developers must
  know to read `request.app.state` rather than a module global.
- If `get_engine()` raises an exception during startup (e.g., SSH credentials invalid),
  the application will fail to start rather than degrading gracefully. This is the
  correct behaviour for a hard dependency.

**References:** FastAPI lifespan docs, Python asyncio docs (asyncio.to_thread, Python 3.9+)
