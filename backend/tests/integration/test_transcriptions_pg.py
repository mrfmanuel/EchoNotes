"""#12: audio upload → transcript against a real Postgres (fake provider, never Groq)."""

import uuid
from collections.abc import Callable
from datetime import datetime

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Transcript
from app.transcription import Transcriber, get_transcriber
from tests.project_utils import at, set_timestamps
from tests.transcription_utils import provider_error, provider_timeout, upload

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def _project(client: httpx2.AsyncClient, name: str) -> str:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


async def test_upload_creates_transcript_and_bumps_project_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project_id = await _project(pg_client, "Física")
    await set_timestamps(pg_session, project_id, created_at=at(1), updated_at=at(1))

    response = await upload(
        pg_client, project_id, "Clase 1.webm", b"a" * 32_000, "audio/webm", language="es"
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["title"], body["slug"], body["language"]) == ("Clase 1", "clase-1", "es")
    assert (body["duration_seconds"], body["provider"]) == (2.0, "fake")
    assert body["text"] == "[fake transcript] Clase 1.webm (32000 bytes)"
    row = await pg_session.get(Transcript, uuid.UUID(body["id"]))
    assert row is not None
    assert (row.source_filename, row.project_id) == ("Clase 1.webm", uuid.UUID(project_id))
    pg_session.expire_all()
    project = await pg_session.get(Project, uuid.UUID(project_id))
    assert project is not None and project.updated_at > at(1)
    detail = (await pg_client.get(f"/api/projects/{project_id}")).json()
    assert [t["id"] for t in detail["transcripts"]] == [body["id"]]
    assert datetime.fromisoformat(detail["updated_at"]) > at(1)


@pytest.mark.parametrize(
    ("make_stub", "status_code"),
    [(provider_error, 502), (provider_timeout, 504)],
    ids=["error", "timeout"],
)
async def test_provider_failure_stores_nothing_on_postgres(
    pg_app: FastAPI,
    pg_client: httpx2.AsyncClient,
    pg_session: AsyncSession,
    make_stub: Callable[[], Transcriber],
    status_code: int,
) -> None:
    stub = make_stub()
    pg_app.dependency_overrides[get_transcriber] = lambda: stub
    project_id = await _project(pg_client, "Failures")

    response = await upload(pg_client, project_id)

    assert response.status_code == status_code
    assert (await pg_session.execute(select(func.count(Transcript.id)))).scalar_one() == 0


async def test_unknown_project_returns_404_on_postgres(pg_client: httpx2.AsyncClient) -> None:
    response = await upload(pg_client, uuid.uuid4())

    assert response.status_code == 404
