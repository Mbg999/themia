"""
Ollama embedding helper for query-time embeddings.

Uses bge-m3 (1024 dimensions) via the Ollama Python client.
The ollama.Client is a module-level singleton keyed to OLLAMA_HOST;
it is rebuilt whenever the env var changes.

Retry strategy: up to 2 retries on transient failures with a fixed 5-second
delay between attempts.  Non-retryable failures (ollama.ResponseError with a
4xx status code) are re-raised immediately without retrying.

Thread-safety: _ollama_client is only written inside _get_ollama_client(),
which rebuilds atomically based on the current OLLAMA_HOST value.
"""
from __future__ import annotations

import os
import time

import ollama

_DEFAULT_HOST = "http://localhost:11434"
_EMBED_MODEL = "bge-m3"
_MAX_RETRIES = 2
_RETRY_DELAY = 5  # seconds

# Module-level singletons — reset to None in tests via direct attribute access
_ollama_client: ollama.Client | None = None
_ollama_client_host: str | None = None  # tracks which host the current client was built for


def _get_ollama_client() -> ollama.Client:
    """Return (or rebuild) the module-level ollama.Client singleton.

    Reads OLLAMA_HOST from the environment on every call and rebuilds the
    client only when the host changes.  This ensures that tests can rotate
    hosts between calls without requiring an explicit reset.
    """
    global _ollama_client, _ollama_client_host
    host = os.environ.get("OLLAMA_HOST", _DEFAULT_HOST)
    if _ollama_client is None or host != _ollama_client_host:
        _ollama_client = ollama.Client(host=host)
        _ollama_client_host = host
    return _ollama_client


def get_query_embedding(text: str) -> list[float]:
    """Return a 1024-dimensional embedding vector for *text*.

    Retry strategy:
    - Up to ``_MAX_RETRIES`` retries on transient failures.
    - Fixed ``_RETRY_DELAY`` second sleep between attempts.
    - Non-retryable = ``ollama.ResponseError`` with a 4xx ``status_code``
      → re-raised immediately.
    - All other exceptions are treated as transient and retried.

    Parameters
    ----------
    text:
        The query string to embed.

    Returns
    -------
    list[float]
        A list of 1024 float values representing the embedding.

    Raises
    ------
    ollama.ResponseError
        For non-retryable 4xx errors from the Ollama server.
    Exception
        Any other exception after all retries are exhausted.
    """
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            time.sleep(_RETRY_DELAY)
        client = _get_ollama_client()
        try:
            response = client.embed(model=_EMBED_MODEL, input=[text])
            return response["embeddings"][0]
        except Exception as exc:
            # Non-retryable: ollama.ResponseError with 4xx status code.
            # Use duck-typing (hasattr) so the check is robust when ollama is
            # patched with a MagicMock namespace in tests.
            if hasattr(exc, "status_code") and 400 <= exc.status_code < 500:
                raise
            last_exc = exc
            continue

    # All retries exhausted
    raise last_exc
