"""Async engine, session factory and the `get_session` FastAPI dependency."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.telemetry import instrument_engine

POSTGRES_CONNECT_TIMEOUT_SECONDS = 5
# Telemetry labels the pool by this name instead of `driver://host:port/db` (#29).
POOL_LOGGING_NAME = "echonotes"


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine(url: str) -> AsyncEngine:
    """Create an async engine. SQLite (unit tests): foreign keys on, one shared connection.

    Traced by SQLAlchemy instrumentation when telemetry is on (#29)."""
    if url.startswith("sqlite"):
        engine = create_async_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_logging_name=POOL_LOGGING_NAME,
        )
        event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    else:
        engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_logging_name=POOL_LOGGING_NAME,
            connect_args={"connect_timeout": POSTGRES_CONNECT_TIMEOUT_SECONDS},
        )
    instrument_engine(engine)
    return engine


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@lru_cache
def get_engine() -> AsyncEngine:
    return create_engine(get_settings().sqlalchemy_url)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(get_engine())


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """FastAPI dependency for background jobs that open their own sessions (US-22).

    Tests override it together with `get_session` so jobs use the test database."""
    return get_sessionmaker()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, always closed afterwards."""
    async with get_sessionmaker()() as session:
        yield session
