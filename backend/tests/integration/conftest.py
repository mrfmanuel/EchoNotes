"""Integration fixtures: a real Postgres at TEST_DATABASE_URL, migrated once per session.

Tests here are marked `integration` and skipped when TEST_DATABASE_URL is unset.
"""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx2
import pytest
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alembic import command
from app.config import get_settings, normalize_database_url
from app.db.session import create_engine, create_sessionmaker, get_session, get_session_factory
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[2]
TABLES = ("summaries", "screenshot", "transcript", "project")


def alembic_config() -> Config:
    """Alembic config for backend/alembic.ini; the URL comes from DATABASE_URL via settings."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    return normalize_database_url(os.environ["TEST_DATABASE_URL"])


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> Iterator[str]:
    """Run `alembic upgrade head` once per session against the test database."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", database_url)
        get_settings.cache_clear()
        command.upgrade(alembic_config(), "head")
        get_settings.cache_clear()
    yield database_url


@pytest.fixture
def use_test_database(monkeypatch: pytest.MonkeyPatch, database_url: str) -> str:
    """Point DATABASE_URL (and so settings and Alembic) at the test database."""
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    return database_url


@pytest.fixture
async def pg_engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(migrated_database)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
def pg_session_maker(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(pg_engine)


@pytest.fixture
async def pg_session(
    pg_session_maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with pg_session_maker() as session:
        yield session


@pytest.fixture
def pg_app(pg_session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_session_factory] = lambda: pg_session_maker  # summary jobs
    return app


@pytest.fixture
async def pg_client(pg_app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=pg_app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
