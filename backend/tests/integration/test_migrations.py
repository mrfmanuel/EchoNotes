"""#9 / #23: Alembic migrations on a real Postgres."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from alembic import command
from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base
from tests.integration.conftest import TABLES, alembic_config

pytestmark = pytest.mark.integration


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migrations_upgrade_downgrade_base_and_upgrade_again(
    migrated_database: str, use_test_database: str
) -> None:
    config = alembic_config()
    assert set(TABLES) <= _tables(use_test_database)

    command.downgrade(config, "base")
    assert _tables(use_test_database) & set(TABLES) == set()

    command.upgrade(config, "head")
    assert set(TABLES) <= _tables(use_test_database)


def test_migrated_schema_matches_the_models(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()

    assert diff == []
