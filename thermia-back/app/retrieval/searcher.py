"""
Database search helpers — vector (pgvector cosine) and BM25 (tsvector).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import Document


def vector_search(engine: Engine, embedding: list[float], top_k: int = 10) -> list[Document]:
    """Return the *top_k* documents closest to *embedding* by cosine similarity.

    Uses pgvector's ``<=>`` cosine-distance operator.

    Parameters
    ----------
    engine:
        Active SQLAlchemy engine (no live connection required until this call).
    embedding:
        Query embedding vector (1024 floats).
    top_k:
        Number of results to return.

    Returns
    -------
    list[Document]
        ORM Document objects ordered by ascending cosine distance.
    """
    embedding_literal = "[" + ",".join(str(v) for v in embedding) + "]"
    sql = text(
        "SELECT * FROM documents "
        "ORDER BY embedding <=> :emb::vector "
        "LIMIT :k"
    )
    with Session(engine) as session:
        rows = session.execute(sql, {"emb": embedding_literal, "k": top_k}).scalars().all()
        return list(rows)


def bm25_search(engine: Engine, query_text: str, top_k: int = 10) -> list[Document]:
    """Return the *top_k* documents matching *query_text* via full-text search.

    Uses PostgreSQL ``tsvector @@ plainto_tsquery('spanish', ...)`` with
    ``ts_rank`` ordering.

    Parameters
    ----------
    engine:
        Active SQLAlchemy engine.
    query_text:
        Plain-text query string (Spanish).
    top_k:
        Number of results to return.

    Returns
    -------
    list[Document]
        ORM Document objects ordered by descending BM25 rank.
    """
    sql = text(
        "SELECT *, ts_rank(tsvector, plainto_tsquery('spanish', :q)) AS rank "
        "FROM documents "
        "WHERE tsvector @@ plainto_tsquery('spanish', :q) "
        "ORDER BY rank DESC "
        "LIMIT :k"
    )
    with Session(engine) as session:
        rows = session.execute(sql, {"q": query_text, "k": top_k}).scalars().all()
        return list(rows)
