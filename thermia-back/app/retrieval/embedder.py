"""
Cohere embedding helper for query-time embeddings.

Uses embed-multilingual-v3.0 (1024 dimensions) with input_type="search_query".
The cohere.Client is a module-level singleton to avoid rebuilding the HTTP
connection pool on every request. Retries on 429 rate-limit errors with
exponential back-off matching the ingest pipeline's pattern.
"""
from __future__ import annotations

import os
import time

import cohere

# Module-level singleton — avoids connection-pool rebuild on every request
_cohere_client: cohere.Client | None = None

_RETRY_DELAYS = (10, 30, 60)


def _get_client() -> cohere.Client:
    global _cohere_client
    if _cohere_client is None:
        api_key = os.environ.get("COHERE_API_KEY", "")
        if not api_key:
            raise ValueError("COHERE_API_KEY environment variable is required but not set.")
        _cohere_client = cohere.Client(api_key)
    return _cohere_client


def get_query_embedding(text: str) -> list[float]:
    """Return a 1024-dimensional embedding vector for *text*.

    Retries up to ``len(_RETRY_DELAYS)`` times on 429 / rate-limit errors
    with exponential back-off (10 s → 30 s → 60 s).

    Parameters
    ----------
    text:
        The query string to embed.

    Returns
    -------
    list[float]
        A list of 1024 float values representing the embedding.
    """
    client = _get_client()
    last_exc: Exception | None = None
    for delay in (0, *_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            response = client.embed(
                texts=[text],
                model="embed-multilingual-v3.0",
                input_type="search_query",
            )
            return list(response.embeddings[0])
        except Exception as exc:
            if "429" in str(exc) or "rate limit" in str(exc).lower():
                last_exc = exc
                continue
            raise
    raise last_exc  # type: ignore[misc]
