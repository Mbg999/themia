"""
Reciprocal Rank Fusion (RRF) for combining vector and BM25 result lists.

Formula: score(doc) = Σ  1 / (60 + rank_i)
where rank_i is the 0-based rank of the document in result list i.

Results are deduplicated by the ``article`` field in ``metadata_``.
"""
from __future__ import annotations

from app.db.models import Document


def rrf_fusion(
    vector_results: list,
    bm25_results: list,
    top_n: int = 5,
) -> list:
    """Merge *vector_results* and *bm25_results* using RRF, dedup by article.

    Parameters
    ----------
    vector_results:
        Ordered list of Document objects from vector search (rank 0 = best).
    bm25_results:
        Ordered list of Document objects from BM25 search (rank 0 = best).
    top_n:
        Maximum number of results to return.

    Returns
    -------
    list
        Merged, deduplicated Document objects sorted by descending RRF score,
        at most *top_n* entries.
    """
    scores: dict[str, float] = {}
    # Map article key → document object (first seen wins for dedup)
    doc_map: dict[str, object] = {}

    for result_list in (vector_results, bm25_results):
        for rank, doc in enumerate(result_list):
            article = doc.metadata_.get("article", str(id(doc)))
            rrf_score = 1.0 / (60 + rank)
            scores[article] = scores.get(article, 0.0) + rrf_score
            if article not in doc_map:
                doc_map[article] = doc

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [doc_map[article] for article, _ in ranked[:top_n]]
