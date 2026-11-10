"""#13: list/edit/delete/download transcripts against a real Postgres (fake provider)."""

import uuid
from datetime import datetime

import httpx2
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Screenshot, Transcript
from app.services.transcript_format import render_markdown
from tests.project_utils import add_screenshot, add_transcript, at, set_timestamps
from tests.transcription_utils import upload

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def _project(client: httpx2.AsyncClient, name: str = "Física") -> str:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


async def _transcript(client: httpx2.AsyncClient, project_id: str, title: str) -> str:
    response = await upload(client, project_id, "clase.webm", title=title, language="es")
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _age(session: AsyncSession, project_id: str, transcript_id: str) -> None:
    await set_timestamps(session, project_id, created_at=at(1), updated_at=at(1))
    await session.execute(
        update(Transcript).where(Transcript.id == uuid.UUID(transcript_id)).values(updated_at=at(1))
    )
    await session.commit()


async def test_list_transcriptions_newest_first_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project_id = uuid.UUID(await _project(pg_client))
    old_id = (await add_transcript(pg_session, project_id, "Old", created_at=at(1))).id
    new_id = (await add_transcript(pg_session, project_id, "New", created_at=at(2))).id

    response = await pg_client.get(f"/api/projects/{project_id}/transcriptions")

    assert response.status_code == 200
    assert [t["id"] for t in response.json()] == [str(new_id), str(old_id)]
    assert all("text" not in t for t in response.json())


async def test_edit_persists_after_refetch_and_bumps_timestamps_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project_id = await _project(pg_client)
    transcript_id = await _transcript(pg_client, project_id, "Clase 1")
    await _age(pg_session, project_id, transcript_id)

    response = await pg_client.patch(
        f"/api/transcriptions/{transcript_id}",
        json={"title": "  Óptica avanzada ", "text": "Texto editado"},
    )

    assert response.status_code == 200, response.text
    body = (await pg_client.get(f"/api/transcriptions/{transcript_id}")).json()
    assert (body["title"], body["slug"]) == ("Óptica avanzada", "optica-avanzada")
    assert body["text"] == "Texto editado"
    assert datetime.fromisoformat(body["updated_at"]) > at(1)
    project = (await pg_client.get(f"/api/projects/{project_id}")).json()
    assert datetime.fromisoformat(project["updated_at"]) > at(1)


async def test_delete_unlinks_screenshot_and_bumps_project_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project_id = await _project(pg_client)
    transcript_id = await _transcript(pg_client, project_id, "Clase 1")
    screenshot_id = (
        await add_screenshot(pg_session, uuid.UUID(project_id), uuid.UUID(transcript_id))
    ).id
    await _age(pg_session, project_id, transcript_id)

    response = await pg_client.delete(f"/api/transcriptions/{transcript_id}")

    assert response.status_code == 204
    pg_session.expire_all()
    assert await pg_session.get(Transcript, uuid.UUID(transcript_id)) is None
    screenshot = await pg_session.get(Screenshot, screenshot_id)
    assert screenshot is not None and screenshot.transcript_id is None
    project = (await pg_client.get(f"/api/projects/{project_id}")).json()
    assert project["screenshot_count"] == 1 and project["transcript_count"] == 0
    assert datetime.fromisoformat(project["updated_at"]) > at(1)


@pytest.mark.parametrize(
    ("download_format", "content_type"),
    [("md", "text/markdown; charset=utf-8"), ("txt", "text/plain; charset=utf-8")],
)
async def test_download_headers_on_postgres(
    pg_client: httpx2.AsyncClient, download_format: str, content_type: str
) -> None:
    project_id = await _project(pg_client)
    transcript_id = await _transcript(pg_client, project_id, "Física 1")

    response = await pg_client.get(
        f"/api/transcriptions/{transcript_id}/download", params={"format": download_format}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="fisica-1.{download_format}"'
    )


async def test_download_md_matches_shared_renderer_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project_id = await _project(pg_client)
    transcript_id = await _transcript(pg_client, project_id, "Física 1")

    response = await pg_client.get(f"/api/transcriptions/{transcript_id}/download?format=md")

    stored = await pg_session.get(Transcript, uuid.UUID(transcript_id))
    assert stored is not None
    assert response.content == render_markdown(stored).encode("utf-8")
