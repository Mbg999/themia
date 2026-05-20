from __future__ import annotations

import asyncio
from typing import Any

from app.constants.constants import default_invalid_resume_msg, default_not_related_msg
from app.retrieval.context_builder import build_context
from app.retrieval.embedder import get_query_embedding
from app.retrieval.fusion import rrf_fusion
from app.retrieval.llm import analyze_with_llm
from app.retrieval.searcher import bm25_search, vector_search


async def run_analysis(engine: Any, query_text: str) -> dict:
    embedding = get_query_embedding(query_text)
    vector_results, bm25_results = await asyncio.gather(
        asyncio.to_thread(vector_search, engine, embedding, 10),
        asyncio.to_thread(bm25_search, engine, query_text, 10),
    )
    top_docs = rrf_fusion(vector_results, bm25_results, top_n=5)
    context = build_context(top_docs)
    result = await asyncio.to_thread(analyze_with_llm, context, query_text)
    resume = (result.get("resumen") or "").strip().lower()

    invalid_phrases = [
        default_invalid_resume_msg.lower(),
        default_not_related_msg.lower(),
    ]

    should_add_fuentes = not any(phrase in resume for phrase in invalid_phrases)

    result["fuentes"] = [
        {
            **(doc.source_metadata_ or {}),
            "law_id": doc.metadata_.get("law_id", ""),
            "law_title": doc.metadata_.get("law_title", ""),
            "article": doc.metadata_.get("article", ""),
            "section": doc.metadata_.get("section", ""),
            "hierarchy_path": doc.metadata_.get("hierarchy_path", ""),
            "legal_rank": doc.legal_rank or "",
            "status": doc.status or "",
            "jurisdiction": doc.jurisdiction or "",
            "eli": doc.metadata_.get("eli") or "",
        }
        for doc in top_docs
    ] if should_add_fuentes else []

    return result
