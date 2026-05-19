"""
Database search helpers — vector (pgvector cosine) and BM25 (tsvector).
"""
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import Document


def vector_search(engine: Engine, embedding: list[float], top_k: int = 10) -> list[Document]:
    """Return the *top_k* documents closest to *embedding* by cosine similarity.

    Uses pgvector's ``<=>`` cosine-distance operator via SQLAlchemy ORM so that
    the embedding list is serialised correctly without raw SQL parameter conflicts.

    Parameters
    ----------
    engine:
        Active SQLAlchemy engine.
    embedding:
        Query embedding vector (1024 floats).
    top_k:
        Number of results to return.

    Returns
    -------
    list[Document]
        ORM Document objects ordered by ascending cosine distance.
    """
    stmt = (
        select(Document)
        .order_by(Document.embedding.op("<=>")(cast(embedding, Vector(1024))))
        .limit(top_k)
    )
    with Session(engine) as session:
        rows = session.execute(stmt).scalars().all()
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
    tsquery = func.plainto_tsquery("spanish", query_text)
    stmt = (
        select(Document)
        .where(Document.tsvector.op("@@")(tsquery))
        .order_by(func.ts_rank(Document.tsvector, tsquery).desc())
        .limit(top_k)
    )
    with Session(engine) as session:
        rows = session.execute(stmt).scalars().all()
        return list(rows)
