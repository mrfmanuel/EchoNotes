"""#9 session dependency: one session per request, closed afterwards."""

from typing import Annotated

import httpx2
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import session as db_session
from app.db.session import get_session

pytestmark = pytest.mark.anyio


class TrackingSession(AsyncSession):
    instances: list["TrackingSession"] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.closed = False
        TrackingSession.instances.append(self)

    async def close(self) -> None:
        self.closed = True
        await super().close()


async def test_get_session_yields_one_session_per_request_and_closes_it(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    TrackingSession.instances = []
    maker = async_sessionmaker(engine, class_=TrackingSession, expire_on_commit=False)
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: maker)
    app = FastAPI()

    @app.get("/probe")
    async def probe(
        first: Annotated[AsyncSession, Depends(get_session)],
        second: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, bool]:
        return {"same": first is second}

    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/probe")
        second = await client.get("/probe")

    assert first.json() == {"same": True} and second.json() == {"same": True}
    assert len(TrackingSession.instances) == 2
    assert all(s.closed for s in TrackingSession.instances)


def test_engine_url_comes_from_database_url_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    url = db_session.get_engine().url
    assert (url.drivername, url.database) == ("sqlite+aiosqlite", ":memory:")
