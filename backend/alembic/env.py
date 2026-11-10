"""Alembic environment. Runs migrations with a sync psycopg engine.

The URL always comes from `DATABASE_URL` via app settings (never from alembic.ini).
Migration logs use the app's JSON log format on stdout at `LOG_LEVEL` (#41).
"""

from sqlalchemy import create_engine, pool

from alembic import context
from app.config import get_settings
from app.db import models  # noqa: F401  (registers the tables on Base.metadata)
from app.db.base import Base
from app.logging import configure_logging

config = context.config

# Callers that already configured logging (the test fixtures) pass configure_logger=False.
if config.attributes.get("configure_logger", True):
    configure_logging(get_settings().log_level)

target_metadata = Base.metadata


def _database_url() -> str:
    return get_settings().sqlalchemy_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
