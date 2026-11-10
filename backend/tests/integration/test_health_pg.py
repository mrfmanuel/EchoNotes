"""#16 / #23: health reports database ok against a real Postgres."""

import httpx2
import pytest

from app import __version__

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_health_returns_database_ok_against_postgres(pg_client: httpx2.AsyncClient) -> None:
    response = await pg_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": __version__,
        "database": "ok",
        "commit": "unknown",
        "environment": "local",
    }
    assert response.headers["X-Request-ID"]
