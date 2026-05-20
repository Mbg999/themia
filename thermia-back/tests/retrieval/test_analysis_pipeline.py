"""
Unit tests for app.retrieval.analysis_pipeline.run_analysis.

All collaborators (embedder, searcher, fusion, context_builder, llm) are mocked
so these tests run without network, DB, or Ollama access.
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from app.retrieval.analysis_pipeline import run_analysis  # noqa: E402
from app.constants.constants import (  # noqa: E402
    default_invalid_resume_msg,
    default_not_related_msg,
)

_P = "app.retrieval.analysis_pipeline"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(
    *,
    law_id: str = "LEY-1",
    law_title: str = "Ley de Prueba",
    article: str = "Art.1",
    section: str = "Cap.1",
    hierarchy_path: str = "LEY-1 > Cap.1 > Art.1",
    legal_rank: str | None = "ley",
    status: str | None = "vigente",
    jurisdiction: str | None = "ES",
    eli: str | None = "https://eli.example.com/1",
    source_metadata_: dict | None = None,
) -> MagicMock:
    doc = MagicMock()
    doc.metadata_ = {
        "law_id": law_id,
        "law_title": law_title,
        "article": article,
        "section": section,
        "hierarchy_path": hierarchy_path,
        "eli": eli,
    }
    doc.legal_rank = legal_rank
    doc.status = status
    doc.jurisdiction = jurisdiction
    doc.source_metadata_ = source_metadata_
    return doc


def _run_with_mocks(
    *,
    top_docs: list | None = None,
    llm_result: dict | None = None,
    query_text: str = "test legal query",
    engine: MagicMock | None = None,
    mock_refs: dict | None = None,
) -> dict:
    """Run run_analysis under full mock isolation. Returns the result dict.

    Pass *mock_refs* as an empty dict to receive the mock objects after the call
    (useful for asserting call args in caller code).
    """
    top_docs = top_docs or []
    llm_result = llm_result if llm_result is not None else {"resumen": "resultado normal"}
    engine = engine or MagicMock()

    mocks = {
        f"{_P}.get_query_embedding": MagicMock(return_value=[0.1] * 1024),
        f"{_P}.vector_search": MagicMock(return_value=[]),
        f"{_P}.bm25_search": MagicMock(return_value=[]),
        f"{_P}.rrf_fusion": MagicMock(return_value=top_docs),
        f"{_P}.build_context": MagicMock(return_value="context text"),
        f"{_P}.analyze_with_llm": MagicMock(return_value=llm_result),
    }

    with ExitStack() as stack:
        active = {name: stack.enter_context(patch(name, m)) for name, m in mocks.items()}
        result = asyncio.run(run_analysis(engine, query_text))

    if mock_refs is not None:
        mock_refs.update(active)
    return result


# ---------------------------------------------------------------------------
# AP-T1: Collaborator wiring
# ---------------------------------------------------------------------------


class TestCollaboratorWiring:
    """AP-T1 — run_analysis calls each collaborator with the correct arguments."""

    def test_get_query_embedding_called_with_query_text(self):
        refs: dict = {}
        _run_with_mocks(query_text="test query abc", mock_refs=refs)
        refs[f"{_P}.get_query_embedding"].assert_called_once_with("test query abc")

    def test_vector_search_called_with_embedding_and_engine(self):
        """vector_search receives (engine, embedding, 10) via asyncio.to_thread."""
        engine = MagicMock(name="engine")
        refs: dict = {}
        _run_with_mocks(engine=engine, mock_refs=refs)
        vs = refs[f"{_P}.vector_search"]
        args = vs.call_args[0]
        assert args[0] is engine
        assert args[1] == [0.1] * 1024
        assert args[2] == 10

    def test_bm25_search_called_with_query_text_and_engine(self):
        """bm25_search receives (engine, query_text, 10) via asyncio.to_thread."""
        engine = MagicMock(name="engine")
        refs: dict = {}
        _run_with_mocks(engine=engine, query_text="query bm25", mock_refs=refs)
        bs = refs[f"{_P}.bm25_search"]
        args = bs.call_args[0]
        assert args[0] is engine
        assert args[1] == "query bm25"
        assert args[2] == 10

    def test_rrf_fusion_called_with_search_results(self):
        """rrf_fusion receives (vector_results, bm25_results, top_n=5)."""
        refs: dict = {}
        _run_with_mocks(mock_refs=refs)
        rrf = refs[f"{_P}.rrf_fusion"]
        _, kwargs = rrf.call_args
        assert kwargs.get("top_n") == 5

    def test_build_context_called_with_top_docs(self):
        """build_context receives the list returned by rrf_fusion."""
        docs = [_make_doc()]
        refs: dict = {}
        _run_with_mocks(top_docs=docs, mock_refs=refs)
        refs[f"{_P}.build_context"].assert_called_once_with(docs)

    def test_analyze_with_llm_called_with_context_and_query(self):
        """analyze_with_llm receives (context, query_text) via asyncio.to_thread."""
        refs: dict = {}
        _run_with_mocks(query_text="query llm", mock_refs=refs)
        llm = refs[f"{_P}.analyze_with_llm"]
        args = llm.call_args[0]
        assert args[0] == "context text"
        assert args[1] == "query llm"


# ---------------------------------------------------------------------------
# AP-T2: fuentes populated on normal resumen
# ---------------------------------------------------------------------------


class TestFuentesPopulated:
    """AP-T2 — fuentes are built from top_docs when resumen is normal."""

    def test_fuentes_length_matches_top_docs(self):
        docs = [_make_doc(law_id=f"L{i}") for i in range(3)]
        result = _run_with_mocks(top_docs=docs)
        assert len(result["fuentes"]) == 3

    def test_fuentes_contains_law_id(self):
        docs = [_make_doc(law_id="LEY-99")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["law_id"] == "LEY-99"

    def test_fuentes_contains_law_title(self):
        docs = [_make_doc(law_title="Ley Orgánica Test")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["law_title"] == "Ley Orgánica Test"

    def test_fuentes_contains_article(self):
        docs = [_make_doc(article="Artículo 42")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["article"] == "Artículo 42"

    def test_fuentes_contains_section(self):
        docs = [_make_doc(section="Título III")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["section"] == "Título III"

    def test_fuentes_contains_hierarchy_path(self):
        docs = [_make_doc(hierarchy_path="L1 > S1 > A1")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["hierarchy_path"] == "L1 > S1 > A1"

    def test_fuentes_contains_legal_rank(self):
        docs = [_make_doc(legal_rank="real decreto")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["legal_rank"] == "real decreto"

    def test_fuentes_contains_status(self):
        docs = [_make_doc(status="derogado")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["status"] == "derogado"

    def test_fuentes_contains_jurisdiction(self):
        docs = [_make_doc(jurisdiction="CAT")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["jurisdiction"] == "CAT"

    def test_fuentes_contains_eli_from_metadata(self):
        docs = [_make_doc(eli="https://eli.test/42")]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["eli"] == "https://eli.test/42"

    def test_fuentes_source_metadata_merged(self):
        """source_metadata_ dict is spread into the fuente entry."""
        docs = [_make_doc(source_metadata_={"title": "Ley Original", "date": "2020-01-01"})]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["title"] == "Ley Original"
        assert result["fuentes"][0]["date"] == "2020-01-01"

    def test_fuentes_source_metadata_none_does_not_crash(self):
        """source_metadata_ = None → fuente still built without error."""
        docs = [_make_doc(source_metadata_=None)]
        result = _run_with_mocks(top_docs=docs)
        assert len(result["fuentes"]) == 1

    def test_fuentes_empty_when_no_top_docs(self):
        result = _run_with_mocks(top_docs=[])
        assert result["fuentes"] == []


# ---------------------------------------------------------------------------
# AP-T3: fuentes suppressed on invalid resumen
# ---------------------------------------------------------------------------


class TestFuentesSuppressed:
    """AP-T3 — fuentes = [] when resumen signals no valid legal context."""

    def test_suppressed_for_invalid_resume_msg(self):
        docs = [_make_doc()]
        result = _run_with_mocks(
            top_docs=docs,
            llm_result={"resumen": default_invalid_resume_msg},
        )
        assert result["fuentes"] == []

    def test_suppressed_for_not_related_msg(self):
        docs = [_make_doc()]
        result = _run_with_mocks(
            top_docs=docs,
            llm_result={"resumen": default_not_related_msg},
        )
        assert result["fuentes"] == []

    def test_suppressed_case_insensitive(self):
        """Detection is case-insensitive (resumen is lowercased before check)."""
        docs = [_make_doc()]
        result = _run_with_mocks(
            top_docs=docs,
            llm_result={"resumen": default_invalid_resume_msg.upper()},
        )
        assert result["fuentes"] == []

    def test_suppressed_when_phrase_embedded_in_longer_resumen(self):
        """Phrase embedded anywhere in resumen triggers suppression."""
        docs = [_make_doc()]
        result = _run_with_mocks(
            top_docs=docs,
            llm_result={"resumen": f"Nota: {default_not_related_msg} Fin."},
        )
        assert result["fuentes"] == []

    def test_not_suppressed_for_normal_resumen(self):
        """Normal resumen → fuentes populated as usual."""
        docs = [_make_doc()]
        result = _run_with_mocks(
            top_docs=docs,
            llm_result={"resumen": "El contrato cumple los requisitos legales vigentes."},
        )
        assert len(result["fuentes"]) == 1

    def test_not_suppressed_for_empty_resumen(self):
        """Empty resumen doesn't contain invalid phrases → fuentes populated."""
        docs = [_make_doc()]
        result = _run_with_mocks(
            top_docs=docs,
            llm_result={"resumen": ""},
        )
        assert len(result["fuentes"]) == 1

    def test_not_suppressed_when_resumen_key_absent(self):
        """Missing resumen key → treated as empty → fuentes populated."""
        docs = [_make_doc()]
        result = _run_with_mocks(
            top_docs=docs,
            llm_result={"analisis": "ok"},
        )
        assert len(result["fuentes"]) == 1


# ---------------------------------------------------------------------------
# AP-T4: None-safety in fuente field mapping
# ---------------------------------------------------------------------------


class TestFuenteNullSafety:
    """AP-T4 — None values in doc fields map to empty strings, not None."""

    def test_legal_rank_none_becomes_empty_string(self):
        docs = [_make_doc(legal_rank=None)]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["legal_rank"] == ""

    def test_status_none_becomes_empty_string(self):
        docs = [_make_doc(status=None)]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["status"] == ""

    def test_jurisdiction_none_becomes_empty_string(self):
        docs = [_make_doc(jurisdiction=None)]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["jurisdiction"] == ""

    def test_eli_none_in_metadata_becomes_empty_string(self):
        docs = [_make_doc(eli=None)]
        result = _run_with_mocks(top_docs=docs)
        assert result["fuentes"][0]["eli"] == ""

    def test_eli_absent_in_metadata_becomes_empty_string(self):
        doc = _make_doc()
        del doc.metadata_["eli"]
        result = _run_with_mocks(top_docs=[doc])
        assert result["fuentes"][0]["eli"] == ""


# ---------------------------------------------------------------------------
# AP-T5: LLM result passthrough
# ---------------------------------------------------------------------------


class TestLLMResultPassthrough:
    """AP-T5 — non-fuentes keys from analyze_with_llm pass through unchanged."""

    def test_resumen_preserved_in_result(self):
        result = _run_with_mocks(llm_result={"resumen": "texto ok", "analisis": "todo bien"})
        assert result["resumen"] == "texto ok"
        assert result["analisis"] == "todo bien"
