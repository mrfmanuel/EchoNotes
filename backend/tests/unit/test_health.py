"""#16 / US-17 health endpoint with the database check."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI

from app import __version__
from app.api import health as health_module
from app.config import get_settings
from app.db.session import create_engine, create_sessionmaker, get_session
from tests.log_utils import parse_json_logs

pytestmark = pytest.mark.anyio

RENDER_SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
GIT_SHA = "0f1e2d3c4b5a69788796a5b4c3d2e1f0a9b8c7d6"
UNREACHABLE_URL = "postgresql+psycopg://echonotes:Sup3r-S3cret-PW@127.0.0.1:1/echonotes"


class _BrokenSession:
    """Stands in for an AsyncSession whose database is down or hanging."""

    def __init__(self, *, hang: bool = False) -> None:
        self.hang = hang

    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        if self.hang:
            await asyncio.sleep(30)
        raise ConnectionRefusedError("connection refused")


def _set_commit_env(
    monkeypatch: pytest.MonkeyPatch, *, render_git_commit: str | None, git_sha: str | None
) -> None:
    """Set (or unset when None) the two commit sources and drop the cached settings."""
    for name, value in (("RENDER_GIT_COMMIT", render_git_commit), ("GIT_SHA", git_sha)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    get_settings.cache_clear()


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
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "database": "ok",
        "commit": "unknown",
        "environment": "local",
    }


async def test_health_returns_503_degraded_when_database_errors(app: FastAPI) -> None:
    _override(app, _BrokenSession())

    response = await _get(app)

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "version": __version__,
        "database": "error",
        "commit": "unknown",
        "environment": "local",
    }


async def test_health_returns_503_quickly_when_database_hangs(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health_module, "DB_CHECK_TIMEOUT_SECONDS", 0.05)
    _override(app, _BrokenSession(hang=True))

    response = await asyncio.wait_for(_get(app), timeout=5)

    assert response.status_code == 503
    assert response.json()["database"] == "error"


@pytest.mark.parametrize(
    ("render_git_commit", "git_sha", "expected"),
    [
        (RENDER_SHA, GIT_SHA, RENDER_SHA),
        (RENDER_SHA, None, RENDER_SHA),
    ],
)
async def test_health_commit_prefers_render_git_commit(
    client: httpx2.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    render_git_commit: str,
    git_sha: str | None,
    expected: str,
) -> None:
    _set_commit_env(monkeypatch, render_git_commit=render_git_commit, git_sha=git_sha)

    response = await client.get("/api/health")

    assert response.json()["commit"] == expected


@pytest.mark.parametrize("render_git_commit", [None, "", "  "])
async def test_health_commit_falls_back_to_git_sha_when_render_commit_is_unset(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch, render_git_commit: str | None
) -> None:
    _set_commit_env(monkeypatch, render_git_commit=render_git_commit, git_sha=GIT_SHA)

    response = await client.get("/api/health")

    assert response.json()["commit"] == GIT_SHA


@pytest.mark.parametrize(
    ("render_git_commit", "git_sha"), [(None, None), ("", ""), (None, ""), ("", None)]
)
async def test_health_commit_is_unknown_when_neither_is_set(
    client: httpx2.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    render_git_commit: str | None,
    git_sha: str | None,
) -> None:
    _set_commit_env(monkeypatch, render_git_commit=render_git_commit, git_sha=git_sha)

    response = await client.get("/api/health")

    assert response.json()["commit"] == "unknown"


@pytest.mark.parametrize("app_env", ["local", "dev", "prod"])
async def test_health_environment_equals_app_env(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    get_settings.cache_clear()

    response = await client.get("/api/health")

    assert response.json()["environment"] == app_env


async def test_health_environment_defaults_to_local(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.json()["environment"] == "local"


async def test_health_503_also_reports_commit_and_environment(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    _set_commit_env(monkeypatch, render_git_commit=RENDER_SHA, git_sha=None)
    _override(app, _BrokenSession())

    response = await _get(app)

    assert response.status_code == 503
    assert response.json()["commit"] == RENDER_SHA
    assert response.json()["environment"] == "prod"


async def test_health_response_exposes_no_secrets(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_Sup3r-S3cret-key")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)
    get_settings.cache_clear()

    response = await client.get("/api/health")

    assert set(response.json()) == {"status", "version", "database", "commit", "environment"}
    assert "Sup3r-S3cret" not in response.text


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
