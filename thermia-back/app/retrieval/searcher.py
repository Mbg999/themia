"""
Database search helpers — vector (pgvector cosine) and BM25 (tsvector).
"""
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import Document


def vector_search(
    engine: Engine,
    embedding: list[float],
    top_k: int = 10,
    *,
    only_active: bool = True,
) -> list[Document]:
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
    only_active:
        When True (default), exclude documents with a known non-active status
        (e.g. ``derogada``).  Documents with an empty or unknown status are
        included so that laws without frontmatter are not silently dropped.

    Returns
    -------
    list[Document]
        ORM Document objects ordered by ascending cosine distance.
    """
    stmt = select(Document)
    if only_active:
        stmt = stmt.where(Document.status.in_(["vigente", ""]))
    stmt = (
        stmt
        .order_by(Document.embedding.op("<=>")(cast(embedding, Vector(1024))))
        .limit(top_k)
    )
    with Session(engine) as session:
        # probes=1 (pgvector default) scans only 1 of lists lists → ~1% recall.
        # 10 gives good recall/speed balance; tune together with lists in the index.
        session.execute(text("SET LOCAL ivfflat.probes = 10"))
        rows = session.execute(stmt).scalars().all()
        return list(rows)


def bm25_search(
    engine: Engine,
    query_text: str,
    top_k: int = 10,
    *,
    only_active: bool = True,
) -> list[Document]:
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
    only_active:
        When True (default), exclude documents with a known non-active status.
        Documents with an empty or unknown status are included.

    Returns
    -------
    list[Document]
        ORM Document objects ordered by descending BM25 rank.
    """
    tsquery = func.plainto_tsquery("spanish", query_text)
    stmt = select(Document).where(Document.tsvector.op("@@")(tsquery))
    if only_active:
        stmt = stmt.where(Document.status.in_(["vigente", ""]))
    stmt = stmt.order_by(func.ts_rank(Document.tsvector, tsquery).desc()).limit(top_k)
    with Session(engine) as session:
        rows = session.execute(stmt).scalars().all()
        return list(rows)
