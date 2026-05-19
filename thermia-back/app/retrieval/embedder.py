"""
Cohere embedding helper.

Uses the embed-multilingual-v3.0 model (1024 dimensions) with
input_type="search_query" for query-time embeddings.
"""
import os

import cohere


def get_query_embedding(text: str) -> list[float]:
    """Return a 1024-dimensional embedding vector for *text*.

    Parameters
    ----------
    text:
        The query string to embed.

    Returns
    -------
    list[float]
        A list of 1024 float values representing the embedding.
    """
    api_key = os.environ.get("COHERE_API_KEY", "")
    client = cohere.Client(api_key)
    response = client.embed(
        texts=[text],
        model="embed-multilingual-v3.0",
        input_type="search_query",
    )
    return list(response.embeddings[0])
