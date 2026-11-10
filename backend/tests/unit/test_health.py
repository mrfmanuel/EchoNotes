"""#16 / US-17 health endpoint with the database check."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI

from app import __version__
from app.api import health as health_module
from app.db.session import create_engine, create_sessionmaker, get_session
from tests.log_utils import parse_json_logs

pytestmark = pytest.mark.anyio

UNREACHABLE_URL = "postgresql+psycopg://echonotes:Sup3r-S3cret-PW@127.0.0.1:1/echonotes"


class _BrokenSession:
    """Stands in for an AsyncSession whose database is down or hanging."""

    def __init__(self, *, hang: bool = False) -> None:
        self.hang = hang

    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        if self.hang:
            await asyncio.sleep(30)
        raise ConnectionRefusedError("connection refused")


def _override(app: FastAPI, session: object) -> None:
    async def broken() -> AsyncIterator[object]:
        yield session

    app.dependency_overrides[get_session] = broken


async def _get(app: FastAPI) -> httpx2.Response:
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/health")


async def test_health_returns_ok_with_version_when_database_reachable(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "database": "ok"}


async def test_health_returns_503_degraded_when_database_errors(app: FastAPI) -> None:
    _override(app, _BrokenSession())

    response = await _get(app)

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "version": __version__, "database": "error"}


async def test_health_returns_503_quickly_when_database_hangs(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_module, "DB_CHECK_TIMEOUT_SECONDS", 0.05)
    _override(app, _BrokenSession(hang=True))

    response = await asyncio.wait_for(_get(app), timeout=5)

    assert response.status_code == 503
    assert response.json()["database"] == "error"


def test_health_db_check_timeout_is_at_most_two_seconds() -> None:
    assert 0 < health_module.DB_CHECK_TIMEOUT_SECONDS <= 2


async def test_health_unreachable_engine_logs_error_class_only(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(health_module, "DB_CHECK_TIMEOUT_SECONDS", 1.0)
    engine = create_engine(UNREACHABLE_URL)
    maker = create_sessionmaker(engine)

    async def unreachable() -> AsyncIterator[object]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = unreachable
    try:
        response = await _get(app)
    finally:
        await engine.dispose()

    assert response.status_code == 503
    output = capsys.readouterr().out
    assert "Sup3r-S3cret-PW" not in output
    assert "127.0.0.1:1" not in output
    failures = [
        line
        for line in parse_json_logs(output)
        if line["message"] == "database health check failed"
    ]
    assert len(failures) == 1
    assert failures[0]["error_class"]
    assert failures[0]["level"] == "WARNING"
