"""
Unit tests for app.retrieval.embedder (Ollama BGE-M3 implementation).

TDD slices EM-T1 / EM-T3 (see embedder-migration code-generation plan).
"""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest

# Make thermia-back importable without an installed package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


# ---------------------------------------------------------------------------
# Helper — reset module-level singleton state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_embedder_singletons():
    """Reset _ollama_client singleton before every test."""
    import app.retrieval.embedder as mod
    mod._ollama_client = None
    yield
    mod._ollama_client = None


# ---------------------------------------------------------------------------
# EM-T1: Host configuration
# ---------------------------------------------------------------------------


class TestHostConfiguration:
    """EM-T1 — OLLAMA_HOST env var controls client host."""

    def test_default_host(self, monkeypatch):
        """OLLAMA_HOST absent → Client built with http://localhost:11434 and timeout."""
        import app.retrieval.embedder as mod
        monkeypatch.delenv("OLLAMA_HOST", raising=False)

        with patch("app.retrieval.embedder.ollama") as mock_ollama:
            mock_client = MagicMock()
            mock_client.embed.return_value = {"embeddings": [[0.1] * 1024]}
            mock_ollama.Client.return_value = mock_client
            mod.get_query_embedding("hello")

        mock_ollama.Client.assert_called_once_with(
            host="http://localhost:11434", timeout=mod._CLIENT_TIMEOUT
        )

    def test_custom_host(self, monkeypatch):
        """OLLAMA_HOST set to https remote → Client built with that host and timeout."""
        import app.retrieval.embedder as mod
        monkeypatch.setenv("OLLAMA_HOST", "https://my-ollama-server:11434")

        with patch("app.retrieval.embedder.ollama") as mock_ollama:
            mock_client = MagicMock()
            mock_client.embed.return_value = {"embeddings": [[0.1] * 1024]}
            mock_ollama.Client.return_value = mock_client
            mod.get_query_embedding("hello")

        mock_ollama.Client.assert_called_once_with(
            host="https://my-ollama-server:11434", timeout=mod._CLIENT_TIMEOUT
        )


# ---------------------------------------------------------------------------
# Security: SSRF host validation
# ---------------------------------------------------------------------------


class TestHostValidation:
    """S-1 — _validate_host rejects http:// for non-localhost targets."""

    def test_localhost_http_allowed(self):
        from app.retrieval.embedder import _validate_host
        _validate_host("http://localhost:11434")  # must not raise

    def test_localhost_ip_http_allowed(self):
        from app.retrieval.embedder import _validate_host
        _validate_host("http://127.0.0.1:11434")  # must not raise

    def test_remote_https_allowed(self):
        from app.retrieval.embedder import _validate_host
        _validate_host("https://ollama.example.com")  # must not raise

    def test_remote_http_rejected(self, monkeypatch):
        from app.retrieval.embedder import _validate_host
        with pytest.raises(RuntimeError, match="https://"):
            _validate_host("http://ollama.example.com")


# ---------------------------------------------------------------------------
# EM-T3: Embedding success path
# ---------------------------------------------------------------------------


class TestEmbeddingSuccess:
    """EM-T3 — get_query_embedding returns correct 1024-dim vector."""

    def test_embedding_success(self, monkeypatch):
        """Returns 1024-dimensional list[float] from embed response."""
        import app.retrieval.embedder as mod
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        expected = [float(i) / 1024 for i in range(1024)]

        with patch("app.retrieval.embedder.ollama") as mock_ollama:
            mock_client = MagicMock()
            mock_client.embed.return_value = {"embeddings": [expected]}
            mock_ollama.Client.return_value = mock_client
            result = mod.get_query_embedding("test query")

        assert result == expected
        assert len(result) == 1024
        mock_client.embed.assert_called_once_with(model="bge-m3", input=["test query"])


# ---------------------------------------------------------------------------
# EM-T3: Retry behaviour
# ---------------------------------------------------------------------------


class TestRetryBehaviour:
    """EM-T3 — retry logic on transient and non-retryable failures."""

    def test_retry_on_transient(self, monkeypatch):
        """Transient errors → up to 2 retries with 5s delay → succeeds on 3rd attempt."""
        monkeypatch.delenv("OLLAMA_HOST", raising=False)

        success_response = {"embeddings": [[0.1] * 1024]}
        call_count = 0

        def embed_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient connection error")
            return success_response

        import app.retrieval.embedder as mod
        with patch("app.retrieval.embedder.ollama") as mock_ollama:
            mock_client = MagicMock()
            mock_client.embed.side_effect = embed_side_effect
            mock_ollama.Client.return_value = mock_client

            with patch("app.retrieval.embedder.time") as mock_time:
                result = mod.get_query_embedding("hello")

        assert result == [0.1] * 1024
        assert call_count == 3
        # 2 retries → 2 sleep(5) calls
        assert mock_time.sleep.call_count == 2
        mock_time.sleep.assert_called_with(5)

    def test_non_retryable_failure(self, monkeypatch):
        """ollama.ResponseError with 4xx status_code → re-raises immediately (no retry)."""
        monkeypatch.delenv("OLLAMA_HOST", raising=False)

        # Non-retryable detection uses hasattr(exc, "status_code") duck-typing,
        # not isinstance — FakeResponseError simulates that shape.
        class FakeResponseError(Exception):
            def __init__(self, msg, status_code):
                super().__init__(msg)
                self.status_code = status_code

        import app.retrieval.embedder as mod
        with patch("app.retrieval.embedder.ollama") as mock_ollama:
            mock_client = MagicMock()
            mock_client.embed.side_effect = FakeResponseError("bad request", 400)
            mock_ollama.Client.return_value = mock_client

            with patch("app.retrieval.embedder.time") as mock_time:
                with pytest.raises(FakeResponseError):
                    mod.get_query_embedding("hello")

                # No sleep → raised immediately
                mock_time.sleep.assert_not_called()

    def test_retries_exhausted(self, monkeypatch):
        """After 2 retries still failing → raises the exception."""
        monkeypatch.delenv("OLLAMA_HOST", raising=False)

        import app.retrieval.embedder as mod
        with patch("app.retrieval.embedder.ollama") as mock_ollama:
            mock_client = MagicMock()
            mock_client.embed.side_effect = ConnectionError("persistent connection error")
            mock_ollama.Client.return_value = mock_client

            with patch("app.retrieval.embedder.time") as mock_time:
                with pytest.raises(ConnectionError):
                    mod.get_query_embedding("hello")

            # 2 retries → 2 sleep(5) calls before giving up
            assert mock_time.sleep.call_count == 2
