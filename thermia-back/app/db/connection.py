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


def get_engine() -> Engine:
    """Return a SQLAlchemy Engine appropriate for the current environment.

    For THERMIA_ENV=local the returned engine has a `.tunnel` attribute
    holding the active SSHTunnelForwarder instance; callers are responsible
    for calling `engine.tunnel.stop()` during shutdown.
    """
    thermia_env = os.environ.get("THERMIA_ENV", "production")

    if thermia_env == "local":
        ssh_host = os.environ["SSH_HOST"]
        ssh_user = os.environ["SSH_USER"]
        ssh_password = os.environ["SSH_PASSWORD"]
        ssh_remote_bind_port = int(os.environ["SSH_REMOTE_BIND_PORT"])

        db_user = os.environ["DB_USER"]
        db_password = os.environ["DB_PASSWORD"]
        db_name = os.environ["DB_NAME"]

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
        url = f"postgresql+psycopg2://{db_user}:{db_password}@127.0.0.1:{local_port}/{db_name}"
        engine = create_engine(url)
        engine.tunnel = tunnel  # type: ignore[attr-defined]
        return engine

    # production (default)
    database_url = os.environ["DATABASE_URL"]
    return create_engine(database_url)
