"""Unit-test fixtures: a fresh in-memory SQLite schema per test."""

from collections.abc import AsyncIterator, Iterator

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base
from app.db.session import create_engine, create_sessionmaker, get_session
from app.main import create_app
from app.telemetry import setup_telemetry
from tests.telemetry_utils import Capture

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_engine(SQLITE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(engine)


@pytest.fixture
async def session(
    session_maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_maker() as session:
        yield session


@pytest.fixture
def app(session_maker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx2.AsyncClient]:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def telemetry(
    monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine, app: FastAPI
) -> Iterator[Capture]:
    """Telemetry ON for `app`/`client`, exporting to memory (#29). Shut down afterwards.

    Request it before `client` so the app is instrumented before its first request.
    """
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    capture = Capture()
    runtime = setup_telemetry(app, get_settings(), capture.exporters)
    assert runtime is not None
    runtime.instrument_engine(engine)
    capture.runtime = runtime
    yield capture
    runtime.shutdown()
