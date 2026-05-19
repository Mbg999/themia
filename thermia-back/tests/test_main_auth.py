"""
Tests for app.main authentication hardening (P1-SEC-1, P1-SEC-2).

TEST-C: startup raises RuntimeError when API_KEY is missing or too short.
TEST-D: _check_auth uses hmac.compare_digest (constant-time comparison).

Note: app.main depends on pdfplumber and other heavy packages that may not be
installed in the test environment. We stub them via sys.modules inside each
test using a fixture, and restore sys.modules afterwards.
"""
from __future__ import annotations

import inspect
import os
import sys
import types
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

# Ensure thermia-back is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STUB_MODULE_NAMES = [
    "pdfplumber",
    "slowapi",
    "slowapi.errors",
    "slowapi.util",
    "app.db",
    "app.db.connection",
    "app.retrieval.context_builder",
    "app.retrieval.embedder",
    "app.retrieval.fusion",
    "app.retrieval.llm",
    "app.retrieval.searcher",
    "app.config",
]


@contextmanager
def _stubbed_heavy_imports():
    """Context manager: temporarily stub unavailable heavy modules.

    On entry: saves current sys.modules state and installs stubs.
    On exit: restores sys.modules to saved state and evicts app.main.
    """
    originals = {name: sys.modules.get(name) for name in _STUB_MODULE_NAMES}
    original_main = sys.modules.get("app.main")

    for name in _STUB_MODULE_NAMES:
        mod = types.ModuleType(name)
        mod.__dict__.update({
            "Limiter": MagicMock(return_value=MagicMock()),
            "_rate_limit_exceeded_handler": MagicMock(),
            "RateLimitExceeded": type("RateLimitExceeded", (Exception,), {}),
            "get_remote_address": MagicMock(),
            "get_engine": MagicMock(),
            "build_context": MagicMock(),
            "get_query_embedding": MagicMock(),
            "rrf_fusion": MagicMock(),
            "analyze_with_llm": MagicMock(),
            "bm25_search": MagicMock(),
            "vector_search": MagicMock(),
        })
        sys.modules[name] = mod

    try:
        yield
    finally:
        # Restore originals
        for name, orig in originals.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig
        # Evict app.main so that the next import (outside this context) uses
        # real pdfplumber if available, or fails naturally.
        sys.modules.pop("app.main", None)
        if original_main is not None:
            sys.modules["app.main"] = original_main


def _reload_main_with_key(monkeypatch, api_key: str | None) -> types.ModuleType:
    """Reload app.main with the given API_KEY (stubs must already be in place).

    monkeypatch may be None — in that case env var is set/deleted directly
    and NOT restored (caller is responsible for restoration via context).
    """
    if monkeypatch is not None:
        if api_key is None:
            monkeypatch.delenv("API_KEY", raising=False)
        else:
            monkeypatch.setenv("API_KEY", api_key)
    else:
        if api_key is None:
            os.environ.pop("API_KEY", None)
        else:
            os.environ["API_KEY"] = api_key
    sys.modules.pop("app.main", None)
    import app.main
    return app.main


# ---------------------------------------------------------------------------
# TEST-C: startup rejection — short or absent API_KEY
# ---------------------------------------------------------------------------


class TestAPIKeyStartupRejection:
    """TEST-C — app.main raises RuntimeError when API_KEY < 16 chars."""

    def test_missing_api_key_raises_on_import(self, monkeypatch):
        """API_KEY absent → RuntimeError at module load."""
        with _stubbed_heavy_imports():
            with pytest.raises(RuntimeError, match="API_KEY"):
                _reload_main_with_key(monkeypatch, None)

    def test_empty_api_key_raises_on_import(self, monkeypatch):
        """API_KEY='' → RuntimeError at module load."""
        with _stubbed_heavy_imports():
            with pytest.raises(RuntimeError, match="API_KEY"):
                _reload_main_with_key(monkeypatch, "")

    def test_short_api_key_raises_on_import(self, monkeypatch):
        """API_KEY shorter than 16 chars → RuntimeError at module load."""
        with _stubbed_heavy_imports():
            with pytest.raises(RuntimeError, match="API_KEY"):
                _reload_main_with_key(monkeypatch, "short")

    def test_exactly_16_char_key_accepted(self, monkeypatch):
        """API_KEY of exactly 16 characters must not raise."""
        with _stubbed_heavy_imports():
            mod = _reload_main_with_key(monkeypatch, "a" * 16)
            assert mod._API_KEY == "a" * 16

    def test_long_key_accepted(self, monkeypatch):
        """API_KEY longer than 16 chars is accepted normally."""
        with _stubbed_heavy_imports():
            mod = _reload_main_with_key(monkeypatch, "very-long-secure-api-key-xyz-1234")
            assert len(mod._API_KEY) >= 16


# ---------------------------------------------------------------------------
# TEST-D: constant-time comparison
# These tests use inspect.getsource() and _check_auth directly — they do not
# need to reload app.main, but they do need it importable.  We use the same
# stub context so they work even when pdfplumber is absent.
# ---------------------------------------------------------------------------


class TestConstantTimeCompare:
    """TEST-D — _check_auth must use hmac.compare_digest, not plain ==."""

    def test_api_key_uses_constant_time_compare(self):
        """Verify hmac.compare_digest is present in app.main source."""
        with _stubbed_heavy_imports():
            _reload_main_with_key(None, os.environ.get("API_KEY", "test-dev-token-1234"))
            import app.main as m
            src = inspect.getsource(m)
        assert "compare_digest" in src, (
            "app.main._check_auth must use hmac.compare_digest for constant-time "
            "comparison — plain string == is vulnerable to timing attacks."
        )

    def test_check_auth_rejects_wrong_token(self):
        """_check_auth raises HTTP 401 for a token that doesn't match _API_KEY."""
        with _stubbed_heavy_imports():
            _reload_main_with_key(None, os.environ.get("API_KEY", "test-dev-token-1234"))
            import app.main as m
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                m._check_auth("Bearer definitely-wrong-token-xyz")
            assert exc_info.value.status_code == 401

    def test_check_auth_accepts_correct_token(self):
        """_check_auth does not raise when the token matches _API_KEY."""
        with _stubbed_heavy_imports():
            api_key = os.environ.get("API_KEY", "test-dev-token-1234")
            _reload_main_with_key(None, api_key)
            import app.main as m
            # Should not raise
            m._check_auth(f"Bearer {m._API_KEY}")

    def test_check_auth_rejects_missing_header(self):
        """_check_auth raises 401 when Authorization header is None."""
        with _stubbed_heavy_imports():
            _reload_main_with_key(None, os.environ.get("API_KEY", "test-dev-token-1234"))
            import app.main as m
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                m._check_auth(None)
            assert exc_info.value.status_code == 401

    def test_check_auth_rejects_non_bearer_scheme(self):
        """_check_auth raises 401 for non-Bearer auth schemes."""
        with _stubbed_heavy_imports():
            _reload_main_with_key(None, os.environ.get("API_KEY", "test-dev-token-1234"))
            import app.main as m
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                m._check_auth("Basic dXNlcjpwYXNz")
            assert exc_info.value.status_code == 401
