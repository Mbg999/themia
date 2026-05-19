"""
Alembic environment configuration.

For THERMIA_ENV=local: uses get_engine() which opens an SSH tunnel before
connecting (SSH_HOST / SSH_USER / SSH_PASSWORD / SSH_REMOTE_BIND_PORT).

For THERMIA_ENV=production (default): uses get_engine() which reads DATABASE_URL.

Offline mode falls back to DATABASE_URL for SQL script generation only.
"""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

from dotenv import load_dotenv

load_dotenv()

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base from our models to use autogenerate support
from app.db.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script output — no live DB).

    Falls back to DATABASE_URL for URL construction only.
    """
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url", ""))
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using the connection factory.

    Uses app.db.connection.get_engine() so that THERMIA_ENV=local
    automatically opens the SSH tunnel before connecting.
    """
    from app.db.connection import get_engine

    connectable = get_engine()

    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)

            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Stop the SSH tunnel if one was opened (local env only)
        tunnel = getattr(connectable, "tunnel", None)
        if tunnel is not None:
            tunnel.stop()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
