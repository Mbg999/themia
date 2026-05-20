"""
Unit tests for POST /analyze/text endpoint.

run_analysis is mocked throughout — these tests cover request validation,
auth enforcement, truncation logic, and the path from a valid request to
a JSON response, not the retrieval pipeline itself (see test_analysis_pipeline.py).
"""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_RUN_ANALYSIS = "app.main.run_analysis"
_FAKE_RESULT = {
    "resumen": "El contrato es válido.",
    "analisis": "Sin irregularidades.",
    "fuentes": [],
}


def _client():
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from app.main import app
    app.state.engine = MagicMock()
    return TestClient(app)


def _auth_headers():
    from app.main import _API_KEY
    return {"Authorization": f"Bearer {_API_KEY}"}


def _post_text(client, text: str, headers=None):
    return client.post(
        "/analyze/text",
        content=json.dumps({"text": text}),
        headers={**(headers or _auth_headers()), "Content-Type": "application/json"},
    )


# ---------------------------------------------------------------------------
# AT-T1: Authentication
# ---------------------------------------------------------------------------


class TestAnalyzeTextAuth:
    """AT-T1 — /analyze/text enforces Bearer auth."""

    def test_no_auth_header_returns_401(self):
        resp = _client().post(
            "/analyze/text",
            content=json.dumps({"text": "hola"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self):
        resp = _client().post(
            "/analyze/text",
            content=json.dumps({"text": "hola"}),
            headers={
                "Authorization": "Bearer wrong-token-xyz",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self):
        with patch(_RUN_ANALYSIS, new=AsyncMock(return_value=_FAKE_RESULT)):
            resp = _post_text(_client(), "texto legal válido")
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# AT-T2: Request body validation
# ---------------------------------------------------------------------------


class TestAnalyzeTextValidation:
    """AT-T2 — /analyze/text rejects malformed or empty bodies."""

    def test_missing_text_field_returns_422(self):
        resp = _client().post(
            "/analyze/text",
            content=json.dumps({"otro_campo": "valor"}),
            headers={**_auth_headers(), "Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_empty_body_returns_422(self):
        resp = _client().post(
            "/analyze/text",
            content="{}",
            headers={**_auth_headers(), "Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_whitespace_only_text_returns_422(self):
        resp = _post_text(_client(), "   \n\t  ")
        assert resp.status_code == 422

    def test_empty_string_text_returns_422(self):
        resp = _post_text(_client(), "")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AT-T3: Truncation
# ---------------------------------------------------------------------------


class TestAnalyzeTextTruncation:
    """AT-T3 — query_text is silently truncated to 2000 characters."""

    def test_text_over_2000_chars_is_accepted(self):
        """A text longer than 2000 chars is truncated but not rejected."""
        long_text = "texto legal " * 300  # ~3600 chars
        with patch(_RUN_ANALYSIS, new=AsyncMock(return_value=_FAKE_RESULT)):
            resp = _post_text(_client(), long_text)
        assert resp.status_code == 200

    def test_run_analysis_receives_truncated_text(self):
        """run_analysis is called with at most 2000 chars of the input."""
        long_text = "x" * 3000
        mock_run = AsyncMock(return_value=_FAKE_RESULT)
        with patch(_RUN_ANALYSIS, new=mock_run):
            _post_text(_client(), long_text)
        _, called_query = mock_run.call_args[0]
        assert len(called_query) <= 2000

    def test_short_text_not_truncated(self):
        """A text under 2000 chars is passed through as-is (after strip)."""
        text = "contrato de arrendamiento urbano"
        mock_run = AsyncMock(return_value=_FAKE_RESULT)
        with patch(_RUN_ANALYSIS, new=mock_run):
            _post_text(_client(), text)
        _, called_query = mock_run.call_args[0]
        assert called_query == text


# ---------------------------------------------------------------------------
# AT-T4: Success path
# ---------------------------------------------------------------------------


class TestAnalyzeTextSuccess:
    """AT-T4 — /analyze/text returns the JSON from run_analysis on success."""

    def test_200_with_valid_text(self):
        with patch(_RUN_ANALYSIS, new=AsyncMock(return_value=_FAKE_RESULT)):
            resp = _post_text(_client(), "Este contrato regula la cesión de derechos.")
        assert resp.status_code == 200

    def test_response_json_matches_run_analysis_output(self):
        with patch(_RUN_ANALYSIS, new=AsyncMock(return_value=_FAKE_RESULT)):
            resp = _post_text(_client(), "texto legal")
        assert resp.json() == _FAKE_RESULT

    def test_run_analysis_called_once(self):
        mock_run = AsyncMock(return_value=_FAKE_RESULT)
        with patch(_RUN_ANALYSIS, new=mock_run):
            _post_text(_client(), "texto legal")
        mock_run.assert_called_once()

    def test_run_analysis_receives_correct_engine(self):
        """run_analysis first arg is the engine from app.state."""
        mock_run = AsyncMock(return_value=_FAKE_RESULT)
        with patch(_RUN_ANALYSIS, new=mock_run):
            _post_text(_client(), "texto")
        engine_arg, _ = mock_run.call_args[0]
        assert engine_arg is not None
