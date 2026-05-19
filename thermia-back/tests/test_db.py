"""
Unit tests for db-layer.
All 9 tests must pass with no real database connection.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure app is importable from thermia-back root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# DB-T1 tests: FastAPI health endpoint
# ---------------------------------------------------------------------------

def test_health_endpoint():
    """GET /health returns {"status": "ok"}."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# DB-T2 tests: Document model
# ---------------------------------------------------------------------------

def test_document_model_columns():
    """Document has all 5 columns with correct types."""
    from pgvector.sqlalchemy import Vector
    from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
    from app.db.models import Document

    columns = {c.name: c for c in Document.__table__.columns}
    assert "id" in columns
    assert "content" in columns
    assert "embedding" in columns
    assert "tsvector" in columns
    assert "metadata" in columns

    assert isinstance(columns["embedding"].type, Vector)
    assert isinstance(columns["metadata"].type, JSONB)
    assert isinstance(columns["tsvector"].type, TSVECTOR)


def test_embedding_dimension():
    """Vector dimension must be exactly 1024."""
    from pgvector.sqlalchemy import Vector
    from app.db.models import Document

    embedding_col = Document.__table__.c["embedding"]
    assert isinstance(embedding_col.type, Vector)
    assert embedding_col.type.dim == 1024


# ---------------------------------------------------------------------------
# DB-T4 / DB-T5 tests: connection factory
# ---------------------------------------------------------------------------

class TestGetEngineLocalPath:
    """Tests for THERMIA_ENV=local branch (SSH tunnel)."""

    def test_local_creates_ssh_tunnel(self, monkeypatch):
        """get_engine() creates SSHTunnelForwarder with correct SSH args."""
        mock_tunnel = MagicMock()
        mock_tunnel.local_bind_port = 55432

        monkeypatch.setenv("THERMIA_ENV", "local")
        monkeypatch.setenv("SSH_HOST", "bastion.example.com")
        monkeypatch.setenv("SSH_USER", "ubuntu")
        monkeypatch.setenv("SSH_PASSWORD", "secret")
        monkeypatch.setenv("SSH_REMOTE_BIND_PORT", "5432")
        monkeypatch.setenv("DB_USER", "pguser")
        monkeypatch.setenv("DB_PASSWORD", "pgpass")
        monkeypatch.setenv("DB_NAME", "thermia")

        import app.db.connection as conn_mod  # noqa: ensure imported

        with patch.object(conn_mod, "SSHTunnelForwarder", return_value=mock_tunnel) as mock_forwarder_cls:
            with patch.object(conn_mod, "create_engine", return_value=MagicMock()):
                conn_mod.get_engine()

        mock_forwarder_cls.assert_called_once_with(
            "bastion.example.com",
            ssh_username="ubuntu",
            ssh_password="secret",
            remote_bind_address=("127.0.0.1", 5432),
            allow_agent=False,
            host_pkey_directories=[],
        )

    def test_local_tunnel_is_started(self, monkeypatch):
        """SSHTunnelForwarder.start() is called before building the engine."""
        mock_tunnel = MagicMock()
        mock_tunnel.local_bind_port = 55432

        monkeypatch.setenv("THERMIA_ENV", "local")
        monkeypatch.setenv("SSH_HOST", "bastion.example.com")
        monkeypatch.setenv("SSH_USER", "ubuntu")
        monkeypatch.setenv("SSH_PASSWORD", "secret")
        monkeypatch.setenv("SSH_REMOTE_BIND_PORT", "5432")
        monkeypatch.setenv("DB_USER", "pguser")
        monkeypatch.setenv("DB_PASSWORD", "pgpass")
        monkeypatch.setenv("DB_NAME", "thermia")

        import app.db.connection as conn_mod

        with patch.object(conn_mod, "SSHTunnelForwarder", return_value=mock_tunnel):
            with patch.object(conn_mod, "create_engine", return_value=MagicMock()):
                conn_mod.get_engine()

        mock_tunnel.start.assert_called_once()

    def test_local_engine_points_to_tunnel_local_port(self, monkeypatch):
        """Engine URL uses 127.0.0.1, tunnel's local_bind_port, and DB credentials."""
        mock_tunnel = MagicMock()
        mock_tunnel.local_bind_port = 55432

        monkeypatch.setenv("THERMIA_ENV", "local")
        monkeypatch.setenv("SSH_HOST", "bastion.example.com")
        monkeypatch.setenv("SSH_USER", "ubuntu")
        monkeypatch.setenv("SSH_PASSWORD", "secret")
        monkeypatch.setenv("SSH_REMOTE_BIND_PORT", "5432")
        monkeypatch.setenv("DB_USER", "pguser")
        monkeypatch.setenv("DB_PASSWORD", "pgpass")
        monkeypatch.setenv("DB_NAME", "thermia")

        captured_url = {}

        def fake_create_engine(url, **kwargs):
            captured_url["url"] = url
            return MagicMock()

        import app.db.connection as conn_mod

        with patch.object(conn_mod, "SSHTunnelForwarder", return_value=mock_tunnel):
            with patch.object(conn_mod, "create_engine", side_effect=fake_create_engine):
                conn_mod.get_engine()

        # URL.create() returns a SQLAlchemy URL object; inspect its attributes directly
        # so the assertion is password-safe and works regardless of render format.
        from sqlalchemy.engine import URL as _URL
        url = captured_url["url"]
        if isinstance(url, _URL):
            assert url.host == "127.0.0.1"
            assert url.port == 55432
            assert url.username == "pguser"
            assert url.database == "thermia"
        else:
            # Fallback for plain-string URLs (kept for forward-compat)
            url_str = str(url)
            assert "127.0.0.1" in url_str
            assert "55432" in url_str
            assert "pguser" in url_str
            assert "thermia" in url_str


class TestGetEngineProductionPath:
    """Tests for THERMIA_ENV=production branch."""

    def test_production_uses_database_url(self, monkeypatch):
        """get_engine() calls create_engine with DATABASE_URL."""
        monkeypatch.setenv("THERMIA_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
        for var in ("SSH_HOST", "SSH_USER", "SSH_PASSWORD", "SSH_REMOTE_BIND_PORT"):
            monkeypatch.delenv(var, raising=False)

        import app.db.connection as conn_mod

        with patch.object(conn_mod, "SSHTunnelForwarder") as mock_forwarder_cls:
            with patch.object(conn_mod, "create_engine", return_value=MagicMock()) as mock_ce:
                conn_mod.get_engine()

        mock_ce.assert_called_once_with("postgresql://user:pass@host/db")

    def test_production_no_tunnel_created(self, monkeypatch):
        """SSHTunnelForwarder is NOT instantiated on the production path."""
        monkeypatch.setenv("THERMIA_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
        for var in ("SSH_HOST", "SSH_USER", "SSH_PASSWORD", "SSH_REMOTE_BIND_PORT"):
            monkeypatch.delenv(var, raising=False)

        import app.db.connection as conn_mod

        with patch.object(conn_mod, "SSHTunnelForwarder") as mock_forwarder_cls:
            with patch.object(conn_mod, "create_engine", return_value=MagicMock()):
                conn_mod.get_engine()

        mock_forwarder_cls.assert_not_called()


class TestGetEngineDefaults:
    """Tests for default THERMIA_ENV behaviour."""

    def test_default_env_is_production(self, monkeypatch):
        """When THERMIA_ENV is not set the factory falls back to production path."""
        monkeypatch.delenv("THERMIA_ENV", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
        for var in ("SSH_HOST", "SSH_USER", "SSH_PASSWORD", "SSH_REMOTE_BIND_PORT"):
            monkeypatch.delenv(var, raising=False)

        import app.db.connection as conn_mod
        # Reset singleton so the mock is actually called (not the cached engine)
        conn_mod._production_engine = None

        with patch.object(conn_mod, "SSHTunnelForwarder") as mock_forwarder_cls:
            with patch.object(conn_mod, "create_engine", return_value=MagicMock()) as mock_ce:
                conn_mod.get_engine()

        mock_forwarder_cls.assert_not_called()
        mock_ce.assert_called_once_with("postgresql://user:pass@host/db")
        conn_mod._production_engine = None  # clean up for subsequent tests
