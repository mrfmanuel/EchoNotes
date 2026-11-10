"""#9 / #23 / #41: Alembic migrations on a real Postgres."""

import json
import uuid
from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.config import get_settings
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


@pytest.fixture
def empty_schema_url(database_url: str) -> Iterator[str]:
    """A brand-new, empty Postgres schema; connections using the URL only see that schema."""
    schema = f"empty_{uuid.uuid4().hex}"
    engine = create_engine(database_url)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        yield f"{database_url}?options=-csearch_path%3D{schema}"
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_upgrade_head_on_an_empty_database_creates_schema_matching_the_models(
    empty_schema_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _tables(empty_schema_url) == set()
    monkeypatch.setenv("DATABASE_URL", empty_schema_url)
    get_settings.cache_clear()
    config = alembic_config()
    config.attributes["configure_logger"] = True  # like the container: env.py sets up logging
    capsys.readouterr()

    command.upgrade(config, "head")

    assert _tables(empty_schema_url) == {*TABLES, "alembic_version"}
    engine = create_engine(empty_schema_url)
    try:
        with engine.connect() as conn:
            assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
    finally:
        engine.dispose()
    # #41: the migration logs are JSON lines in the app format and never show the URL.
    output = capsys.readouterr()
    records = [json.loads(line) for line in output.out.splitlines() if line.strip()]
    assert output.err == ""
    assert any(r["message"].startswith("Running upgrade") for r in records)
    assert all(r["logger"] and "request_id" in r for r in records)
    assert "echonotes_test@" not in output.out


def test_migrated_schema_matches_the_models(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()

    assert diff == []
