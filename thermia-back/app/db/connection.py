"""
Database connection factory for Thermia.

Behaviour is controlled by the THERMIA_ENV environment variable:

  THERMIA_ENV=local
      Creates an SSHTunnelForwarder using SSH_HOST, SSH_USER, SSH_PASSWORD,
      and SSH_REMOTE_BIND_PORT. The tunnel is started before the engine is
      built (local_bind_port is only available after start()).
      The tunnel instance is attached as `engine.tunnel` for lifecycle
      management by the caller.

  THERMIA_ENV=production  (default when THERMIA_ENV is not set)
      Returns a plain SQLAlchemy Engine from DATABASE_URL.

No connection strings are hardcoded here — all values come from os.environ.
python-dotenv is loaded in app.config; importing app.config is optional but
recommended so that .env values are available.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sshtunnel import SSHTunnelForwarder

# Production engine is a module-level singleton — connection pool is reused
# across requests instead of being rebuilt on every call.
_production_engine: Engine | None = None


def get_engine() -> Engine:
    """Return a SQLAlchemy Engine appropriate for the current environment.

    For THERMIA_ENV=local the returned engine has a `.tunnel` attribute
    holding the active SSHTunnelForwarder instance; callers are responsible
    for calling `engine.tunnel.stop()` during shutdown.
    """
    thermia_env = os.environ.get("THERMIA_ENV", "production")

    if thermia_env == "local":
        from urllib.parse import quote_plus
        from sqlalchemy.engine import URL as _URL

        ssh_host = os.environ.get("SSH_HOST")
        if not ssh_host:
            raise ValueError("SSH_HOST is required when THERMIA_ENV=local")
        ssh_user = os.environ.get("SSH_USER")
        if not ssh_user:
            raise ValueError("SSH_USER is required when THERMIA_ENV=local")
        ssh_password = os.environ.get("SSH_PASSWORD")
        if not ssh_password:
            raise ValueError("SSH_PASSWORD is required when THERMIA_ENV=local")
        _raw_port = os.environ.get("SSH_REMOTE_BIND_PORT")
        if not _raw_port:
            raise ValueError("SSH_REMOTE_BIND_PORT is required when THERMIA_ENV=local")
        ssh_remote_bind_port = int(_raw_port)

        db_user = os.environ.get("DB_USER")
        if not db_user:
            raise ValueError("DB_USER is required when THERMIA_ENV=local")
        db_password = os.environ.get("DB_PASSWORD")
        if not db_password:
            raise ValueError("DB_PASSWORD is required when THERMIA_ENV=local")
        db_name = os.environ.get("DB_NAME")
        if not db_name:
            raise ValueError("DB_NAME is required when THERMIA_ENV=local")

        tunnel = SSHTunnelForwarder(
            ssh_host,
            ssh_username=ssh_user,
            ssh_password=ssh_password,
            remote_bind_address=("127.0.0.1", ssh_remote_bind_port),
            allow_agent=False,         # don't try the local SSH agent
            host_pkey_directories=[],  # don't scan ~/.ssh/ for key files
        )
        tunnel.start()  # local_bind_port is only available after start()

        local_port = tunnel.local_bind_port
        url = _URL.create(
            "postgresql+psycopg2",
            username=db_user,
            password=db_password,
            host="127.0.0.1",
            port=local_port,
            database=db_name,
        )
        engine = create_engine(url)
        engine.tunnel = tunnel  # type: ignore[attr-defined]
        return engine

    # production (default) — return cached singleton
    global _production_engine
    if _production_engine is None:
        _production_engine = create_engine(os.environ["DATABASE_URL"])
    return _production_engine
