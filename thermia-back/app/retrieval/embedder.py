"""
Cohere embedding helper for query-time embeddings.

Uses embed-multilingual-v3.0 (1024 dimensions) with input_type="search_query".
The cohere.Client is a module-level singleton tied to the active pool key;
it is rebuilt whenever the KeyPool rotates to a new key.

Retries on 429 / rate-limit errors with exponential back-off.  After the
in-key retry budget (_RETRY_DELAYS) is exhausted the pool is asked to
rotate.  Non-rotating failures (e.g. 400, 401, 403) are re-raised
immediately without touching the pool.

Thread-safety: KeyPool is internally locked; _cohere_client is only written
inside _get_client() which rebuilds atomically based on the pool's current
key.
"""
from __future__ import annotations

import time

import cohere

from app.retrieval.key_pool import (
    AllKeysExhaustedError,
    KeyPool,
    classify_failure,
)

# Module-level singletons — reset to None in tests via direct attribute access
_cohere_client: cohere.Client | None = None
_cohere_pool: KeyPool | None = None

_RETRY_DELAYS = (10, 30, 60)


def get_cohere_pool() -> KeyPool:
    """Return (or initialise) the module-level Cohere KeyPool singleton.

    On first call reads keys from the environment via
    ``KeyPool.from_env("cohere")``.  Subsequent calls return the same
    instance so that ingest.py and the FastAPI route handlers share a
    single pool.
    """
    global _cohere_pool
    if _cohere_pool is None:
        _cohere_pool = KeyPool.from_env("cohere")
    return _cohere_pool


def _get_client() -> cohere.Client:
    """Return a cohere.Client for the pool's currently active key.

    Rebuilds the client when the singleton is None (first call or after
    a rotation reset).
    """
    global _cohere_client
    pool = get_cohere_pool()
    active_key = pool.current()

    # Rebuild if not yet created (first call) or after a rotation
    if _cohere_client is None:
        _cohere_client = cohere.Client(active_key)
    return _cohere_client


def get_query_embedding(text: str) -> list[float]:
    """Return a 1024-dimensional embedding vector for *text*.

    Retry strategy:
    1. In-key retries: up to ``len(_RETRY_DELAYS)`` attempts on the current
       key with exponential back-off (10 s → 30 s → 60 s) for 429 / rate-
       limit errors.
    2. Pool rotation: once the in-key budget is exhausted, call
       ``pool.mark_failed`` to rotate to the next healthy key, rebuild the
       client, and attempt once on the new key.
    3. Non-rotating failures (400, 401, 403, …): re-raised immediately
       without rotating.

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
    AllKeysExhaustedError
        When every key in the pool has been exhausted.
    Exception
        Original exception for non-rotating failure signals.
    """
    global _cohere_client

    pool = get_cohere_pool()

    last_exc: Exception | None = None
    for delay in (0, *_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        client = _get_client()
        try:
            response = client.embed(
                texts=[text],
                model="embed-multilingual-v3.0",
                input_type="search_query",
            )
            return list(response.embeddings[0])
        except Exception as exc:
            reason = classify_failure(exc)
            if reason is None:
                # Non-rotating failure — re-raise immediately
                raise
            # Rotating failure — collect and retry in-key
            last_exc = exc
            continue

    # In-key budget exhausted — rotate to next key
    assert last_exc is not None
    pool.mark_failed(classify_failure(last_exc))  # may raise AllKeysExhaustedError
    # Rebuild client with new key
    _cohere_client = None

    # One final attempt on the new key (let exceptions propagate)
    client = _get_client()
    response = client.embed(
        texts=[text],
        model="embed-multilingual-v3.0",
        input_type="search_query",
    )
    return list(response.embeddings[0])
