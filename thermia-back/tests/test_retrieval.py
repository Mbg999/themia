"""
Unit tests for retrieval-api.
All tests run without network or DB access (fully mocked).
"""
import io
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf_bytes(text: str) -> bytes:
    """Return a minimal in-memory PDF whose page contains *text*."""
    # We'll patch pdfplumber.open so the bytes only need to be valid enough
    # to create an UploadFile — pdfplumber will be mocked in most tests.
    # For the non-mocked path test we embed a real single-page PDF stub.
    return b"%PDF-1.4 stub content " + text.encode()


# ---------------------------------------------------------------------------
# RT-T1 / RT-T2: Auth — no header / wrong token → 401
# ---------------------------------------------------------------------------

class TestAnalyzeAuth:
    """Authentication checks for POST /analyze."""

    def _client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_no_auth_header_returns_401(self):
        """POST /analyze without Authorization header → 401."""
        client = self._client()
        data = {"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
        resp = client.post("/analyze", files=data)
        assert resp.status_code == 401

    def test_wrong_bearer_token_returns_401(self, monkeypatch):
        """POST /analyze with wrong Bearer token → 401."""
        monkeypatch.setenv("API_KEY", "correct-key")
        client = self._client()
        data = {"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
        resp = client.post(
            "/analyze",
            files=data,
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# RT-T3: Non-PDF upload → 422
# ---------------------------------------------------------------------------

class TestAnalyzeFileType:
    """File-type validation for POST /analyze."""

    def test_non_pdf_returns_422(self, monkeypatch):
        """POST /analyze with a text/plain file → 422."""
        monkeypatch.setenv("API_KEY", "test-key")
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        data = {"file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")}
        resp = client.post(
            "/analyze",
            files=data,
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# RT-T4: Empty / non-legal PDF → 422 with Spanish message
# ---------------------------------------------------------------------------

class TestAnalyzeLegalGuard:
    """Legal-content guard for POST /analyze."""

    def _client_and_env(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "test-key")
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_empty_pdf_returns_422_spanish(self, monkeypatch):
        """POST /analyze with an empty-text PDF → 422 with Spanish detail."""
        client = self._client_and_env(monkeypatch)

        mock_page = MagicMock()
        mock_page.extract_text.return_value = ""
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open", return_value=mock_pdf):
            data = {"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
            resp = client.post(
                "/analyze",
                files=data,
                headers={"Authorization": "Bearer test-key"},
            )

        assert resp.status_code == 422
        assert "legal" in resp.json()["detail"].lower()

    def test_non_legal_pdf_returns_422_spanish(self, monkeypatch):
        """POST /analyze with a PDF whose text has no Spanish legal keywords → 422."""
        client = self._client_and_env(monkeypatch)

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is a cooking recipe with no legal content."
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]

        with patch("pdfplumber.open", return_value=mock_pdf):
            data = {"file": ("doc.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
            resp = client.post(
                "/analyze",
                files=data,
                headers={"Authorization": "Bearer test-key"},
            )

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "El documento no contiene contenido legal reconocible" in detail


# ---------------------------------------------------------------------------
# RT-T5: rrf_fusion — correct merge order, deduped by article
# ---------------------------------------------------------------------------

class TestRRFFusion:
    """Tests for rrf_fusion in app.retrieval.fusion."""

    def _make_doc(self, article: str, content: str = "x") -> MagicMock:
        doc = MagicMock()
        doc.metadata_ = {"article": article}
        doc.content = content
        return doc

    def test_rrf_deduplicates_by_article(self):
        """Overlap between vector and BM25 results is deduplicated by article."""
        from app.retrieval.fusion import rrf_fusion

        a = self._make_doc("art-1")
        b = self._make_doc("art-2")
        c = self._make_doc("art-3")

        # a appears in both lists — should appear only once in output
        vector_results = [a, b]
        bm25_results = [a, c]

        result = rrf_fusion(vector_results, bm25_results, top_n=5)
        articles = [doc.metadata_["article"] for doc in result]
        assert len(articles) == len(set(articles)), "Duplicate articles found"
        assert "art-1" in articles

    def test_rrf_top_n_respected(self):
        """rrf_fusion returns at most top_n documents."""
        from app.retrieval.fusion import rrf_fusion

        docs_v = [self._make_doc(f"v-{i}") for i in range(10)]
        docs_b = [self._make_doc(f"b-{i}") for i in range(10)]
        result = rrf_fusion(docs_v, docs_b, top_n=5)
        assert len(result) <= 5

    def test_rrf_higher_ranked_item_wins(self):
        """Document ranked #1 in both lists has highest RRF score."""
        from app.retrieval.fusion import rrf_fusion

        top = self._make_doc("top-article")
        low = self._make_doc("low-article")
        other = self._make_doc("other-article")

        # top is rank-0 in both; low is rank-1 in vector only; other rank-1 in bm25 only
        vector_results = [top, low]
        bm25_results = [top, other]

        result = rrf_fusion(vector_results, bm25_results, top_n=5)
        assert result[0].metadata_["article"] == "top-article"

    def test_rrf_formula(self):
        """RRF score = sum(1/(60+rank)) across all lists where doc appears."""
        from app.retrieval.fusion import rrf_fusion

        a = self._make_doc("a")
        b = self._make_doc("b")
        # a: rank 0 in both → score = 1/60 + 1/60 = 2/60
        # b: rank 1 in vector only → score = 1/61
        vector_results = [a, b]
        bm25_results = [a]

        result = rrf_fusion(vector_results, bm25_results, top_n=5)
        assert result[0].metadata_["article"] == "a"
        assert result[1].metadata_["article"] == "b"


# ---------------------------------------------------------------------------
# RT-T6: build_context — correct format string
# ---------------------------------------------------------------------------

class TestBuildContext:
    """Tests for build_context in app.retrieval.context_builder."""

    def _make_doc(self, law_id, article, section, content):
        doc = MagicMock()
        doc.metadata_ = {"law_id": law_id, "article": article, "section": section}
        doc.content = content
        return doc

    def test_format_contains_law_article_section(self):
        """build_context formats each chunk with [law | article | section]."""
        from app.retrieval.context_builder import build_context

        doc = self._make_doc("LEY-1", "Art.5", "Cap.2", "Some legal text.")
        ctx = build_context([doc])

        assert "[LEY-1 | Art.5 | Cap.2]" in ctx
        assert "Some legal text." in ctx

    def test_format_separator(self):
        """build_context separates chunks with ---."""
        from app.retrieval.context_builder import build_context

        doc1 = self._make_doc("L1", "A1", "S1", "Text one.")
        doc2 = self._make_doc("L2", "A2", "S2", "Text two.")
        ctx = build_context([doc1, doc2])

        assert "---" in ctx
        assert "Text one." in ctx
        assert "Text two." in ctx

    def test_empty_list_returns_empty_string(self):
        """build_context on empty list returns empty string."""
        from app.retrieval.context_builder import build_context
        assert build_context([]) == ""


# ---------------------------------------------------------------------------
# RT-T7: vector_search — mock DB, assert ORM call
# ---------------------------------------------------------------------------

class TestVectorSearch:
    """Tests for vector_search in app.retrieval.searcher."""

    def test_vector_search_returns_list(self):
        """vector_search returns a list of ORM objects."""
        from app.retrieval.searcher import vector_search

        mock_engine = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        doc1 = MagicMock()
        doc2 = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [doc1, doc2]

        with patch("app.retrieval.searcher.Session", return_value=mock_session):
            result = vector_search(mock_engine, [0.1] * 1024, top_k=10)

        assert isinstance(result, list)
        assert len(result) == 2

    def test_vector_search_calls_execute(self):
        """vector_search calls session.execute (i.e. issues a query)."""
        from app.retrieval.searcher import vector_search

        mock_engine = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with patch("app.retrieval.searcher.Session", return_value=mock_session):
            vector_search(mock_engine, [0.1] * 1024, top_k=5)

        mock_session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# RT-T8: bm25_search — mock DB, assert ORM call
# ---------------------------------------------------------------------------

class TestBM25Search:
    """Tests for bm25_search in app.retrieval.searcher."""

    def test_bm25_search_returns_list(self):
        """bm25_search returns a list of ORM objects."""
        from app.retrieval.searcher import bm25_search

        mock_engine = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with patch("app.retrieval.searcher.Session", return_value=mock_session):
            result = bm25_search(mock_engine, "artículo ley decreto", top_k=10)

        assert isinstance(result, list)

    def test_bm25_search_calls_execute(self):
        """bm25_search calls session.execute (i.e. issues a query)."""
        from app.retrieval.searcher import bm25_search

        mock_engine = MagicMock()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with patch("app.retrieval.searcher.Session", return_value=mock_session):
            bm25_search(mock_engine, "some query", top_k=5)

        mock_session.execute.assert_called_once()
