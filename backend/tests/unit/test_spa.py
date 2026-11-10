"""#22 the built SPA is served by FastAPI with an index.html fallback for client routes."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.session import get_session
from app.main import create_app

pytestmark = pytest.mark.anyio

INDEX_HTML = "<!doctype html><title>EchoNotes test SPA</title><div id=root></div>"
ASSET_JS = "console.log('bundle')"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text(ASSET_JS, encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    return dist


def _create_app(
    monkeypatch: pytest.MonkeyPatch,
    session_maker: async_sessionmaker[AsyncSession],
    static_dir: Path | str | None,
) -> FastAPI:
    if static_dir is not None:
        monkeypatch.setenv("STATIC_DIR", str(static_dir))
    get_settings.cache_clear()
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
async def spa_client(
    monkeypatch: pytest.MonkeyPatch,
    session_maker: async_sessionmaker[AsyncSession],
    static_dir: Path,
) -> AsyncIterator[httpx2.AsyncClient]:
    app = _create_app(monkeypatch, session_maker, static_dir)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_root_returns_index_html(spa_client: httpx2.AsyncClient) -> None:
    response = await spa_client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == INDEX_HTML
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "path", ["/projects/3f1c2b9e-0000-4000-8000-000000000000", "/transcripts/x", "/unknown/deep"]
)
async def test_client_routes_fall_back_to_index_html(
    spa_client: httpx2.AsyncClient, path: str
) -> None:
    response = await spa_client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX_HTML


async def test_assets_are_served_as_static_files(spa_client: httpx2.AsyncClient) -> None:
    response = await spa_client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == ASSET_JS
    assert "javascript" in response.headers["content-type"]


async def test_missing_asset_is_404_not_index_html(spa_client: httpx2.AsyncClient) -> None:
    response = await spa_client.get("/assets/missing.js")

    assert response.status_code == 404
    assert INDEX_HTML not in response.text


async def test_root_level_public_file_is_served(spa_client: httpx2.AsyncClient) -> None:
    response = await spa_client.get("/favicon.svg")

    assert response.status_code == 200
    assert response.text == "<svg/>"


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/unknown", "/api/projects/x/nope"])
async def test_unknown_api_paths_return_json_404_not_index_html(
    spa_client: httpx2.AsyncClient, path: str
) -> None:
    response = await spa_client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not Found", "code": "not_found"}


async def test_api_routes_still_work_with_spa_mounted(spa_client: httpx2.AsyncClient) -> None:
    response = await spa_client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


async def test_projects_api_is_not_shadowed_by_the_spa_catch_all(
    spa_client: httpx2.AsyncClient,
) -> None:
    listed = await spa_client.get("/api/projects")
    missing = await spa_client.get("/api/projects/3f1c2b9e-0000-4000-8000-000000000000")

    assert listed.status_code == 200
    assert listed.json() == []
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


async def test_path_traversal_outside_static_dir_returns_index_html(
    spa_client: httpx2.AsyncClient,
) -> None:
    response = await spa_client.get("/%2E%2E/secret.txt")

    assert response.status_code == 200
    assert "outside" not in response.text


async def test_spa_catch_all_is_not_in_openapi(spa_client: httpx2.AsyncClient) -> None:
    paths = (await spa_client.get("/openapi.json")).json()["paths"]

    assert "/api/health" in paths
    assert all(path.startswith("/api/") for path in paths)


@pytest.mark.parametrize("static_dir_value", [None, "", "missing-dir"])
async def test_without_static_dir_the_app_serves_the_api_only(
    monkeypatch: pytest.MonkeyPatch,
    session_maker: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    static_dir_value: str | None,
) -> None:
    value = str(tmp_path / static_dir_value) if static_dir_value else static_dir_value
    app = _create_app(monkeypatch, session_maker, value)
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        health = await client.get("/api/health")

    assert root.status_code == 404
    assert root.headers["content-type"] == "application/json"
    assert health.status_code == 200
