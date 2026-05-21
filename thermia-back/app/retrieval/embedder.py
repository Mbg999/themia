"""
Ollama embedding helper for query-time embeddings.

Model: bge-m3 (1024 dimensions) via the Ollama Python client.
Host: OLLAMA_HOST env var (default http://localhost:11434); non-localhost
      hosts must use https:// — RuntimeError raised otherwise.
Retry: up to 2 retries on transient failures, fixed 5 s delay.
       Non-retryable 4xx errors re-raised immediately.
Timeout: 30 s on the HTTP client to prevent thread-pool exhaustion.
Thread-safety: double-checked locking in _get_ollama_client().
"""
from __future__ import annotations

import os
import threading
import time
from urllib.parse import urlparse

import ollama

_DEFAULT_HOST = "http://localhost:11434"
_EMBED_MODEL = "bge-m3"
_MAX_RETRIES = 2
_RETRY_DELAY = 5  # seconds
_EXPECTED_DIM = 1024
_CLIENT_TIMEOUT = 30.0  # seconds — prevents thread-pool exhaustion on hung server

# Module-level singleton — reset to None in tests via direct attribute access
_ollama_client: ollama.Client | None = None
_ollama_lock = threading.Lock()


def _validate_host(host: str) -> None:
    """Raise RuntimeError if a non-localhost host does not use https://."""
    parsed = urlparse(host)
    hostname = parsed.hostname or ""
    is_local = hostname in ("localhost", "127.0.0.1", "::1", "host.docker.internal") or hostname.startswith("127.")
    if not is_local and parsed.scheme != "https":
        raise RuntimeError(
            f"OLLAMA_HOST must use https:// for non-localhost targets, got: {host!r}"
        )


def _get_ollama_client() -> ollama.Client:
    """Return (or rebuild) the module-level ollama.Client singleton.

    Uses double-checked locking so that concurrent FastAPI worker threads
    never build the client more than once.
    """
    global _ollama_client
    if _ollama_client is None:
        with _ollama_lock:
            if _ollama_client is None:
                host = os.environ.get("OLLAMA_HOST", _DEFAULT_HOST)
                _validate_host(host)
                _ollama_client = ollama.Client(host=host, timeout=_CLIENT_TIMEOUT)
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
    RuntimeError
        If OLLAMA_HOST uses an insecure scheme for a non-localhost target,
        or if the returned embedding has unexpected dimensionality.
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
            vec = response["embeddings"][0]
            if len(vec) != _EXPECTED_DIM:
                raise ValueError(
                    f"Expected {_EXPECTED_DIM}-dim embedding from Ollama, got {len(vec)}"
                )
            return vec
        except Exception as exc:
            # Non-retryable: ollama.ResponseError with 4xx status code.
            # Use duck-typing (hasattr) so the check is robust when ollama is
            # patched with a MagicMock namespace in tests.
            if hasattr(exc, "status_code") and 400 <= exc.status_code < 500:
                raise
            last_exc = exc

    raise last_exc or RuntimeError("all retries exhausted with no recorded exception")
