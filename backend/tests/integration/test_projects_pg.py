"""#10 / #23: projects API against a real Postgres (CRUD, slugs, cascade, ordering)."""

import asyncio
import uuid
from datetime import datetime
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Screenshot, Transcript
from app.services import projects as project_service
from tests.project_utils import add_screenshot, add_transcript, at, set_timestamps

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def _create(client: httpx2.AsyncClient, name: str) -> dict[str, Any]:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def test_project_crud_flow_on_postgres(pg_client: httpx2.AsyncClient) -> None:
    created = await _create(pg_client, "  Clase de Física  ")
    assert (created["name"], created["slug"]) == ("Clase de Física", "clase-de-fisica")
    assert (created["transcript_count"], created["screenshot_count"]) == (0, 0)

    detail = (await pg_client.get(f"/api/projects/{created['id']}")).json()
    assert (detail["transcripts"], detail["screenshots"]) == ([], [])

    renamed = await pg_client.patch(f"/api/projects/{created['id']}", json={"name": "Física II"})
    assert renamed.status_code == 200
    assert (renamed.json()["name"], renamed.json()["slug"]) == ("Física II", "clase-de-fisica")
    assert datetime.fromisoformat(renamed.json()["updated_at"]) > datetime.fromisoformat(
        created["updated_at"]
    )

    assert [p["id"] for p in (await pg_client.get("/api/projects")).json()] == [created["id"]]
    assert (await pg_client.delete(f"/api/projects/{created['id']}")).status_code == 204
    second = await pg_client.delete(f"/api/projects/{created['id']}")
    assert second.status_code == 404
    assert second.json() == {"detail": "Project not found", "code": "not_found"}
    assert (await pg_client.get("/api/projects")).json() == []


async def test_invalid_names_create_no_rows_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    for payload in ({"name": "   "}, {"name": "x" * 101}, {}):
        assert (await pg_client.post("/api/projects", json=payload)).status_code == 422

    assert (await pg_session.execute(select(func.count(Project.id)))).scalar_one() == 0


async def test_slug_collisions_get_suffixes_on_postgres(pg_client: httpx2.AsyncClient) -> None:
    slugs = [(await _create(pg_client, name))["slug"] for name in ("Notes", "notes", "NOTES!")]

    assert slugs == ["notes", "notes-2", "notes-3"]


async def test_slug_unique_constraint_is_enforced_on_postgres(pg_session: AsyncSession) -> None:
    pg_session.add_all([Project(name="A", slug="dup"), Project(name="B", slug="dup")])

    with pytest.raises(IntegrityError):
        await pg_session.commit()


async def test_concurrent_creates_with_same_name_get_unique_slugs_on_postgres(
    pg_client: httpx2.AsyncClient,
) -> None:
    responses = await asyncio.gather(
        *(pg_client.post("/api/projects", json={"name": "Standup"}) for _ in range(5))
    )

    assert [r.status_code for r in responses] == [201] * 5
    slugs = sorted(r.json()["slug"] for r in responses)
    assert slugs == ["standup", "standup-2", "standup-3", "standup-4", "standup-5"]


async def test_delete_cascades_transcripts_and_screenshots_via_api_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    doomed = await _create(pg_client, "Doomed")
    kept = await _create(pg_client, "Kept")
    doomed_id, kept_id = uuid.UUID(doomed["id"]), uuid.UUID(kept["id"])
    transcript = await add_transcript(pg_session, doomed_id)
    await add_screenshot(pg_session, doomed_id, transcript.id)
    await add_transcript(pg_session, kept_id)
    await add_screenshot(pg_session, kept_id)

    assert (await pg_client.delete(f"/api/projects/{doomed_id}")).status_code == 204

    assert set((await pg_session.scalars(select(Transcript.project_id))).all()) == {kept_id}
    assert set((await pg_session.scalars(select(Screenshot.project_id))).all()) == {kept_id}


async def test_list_order_and_counts_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    old = await _create(pg_client, "Old")
    tie_older = await _create(pg_client, "Tie older")
    tie_newer = await _create(pg_client, "Tie newer")
    await set_timestamps(pg_session, old["id"], created_at=at(1), updated_at=at(2))
    await set_timestamps(pg_session, tie_older["id"], created_at=at(1), updated_at=at(8))
    await set_timestamps(pg_session, tie_newer["id"], created_at=at(3), updated_at=at(8))
    old_id = uuid.UUID(old["id"])
    await add_transcript(pg_session, old_id)
    await add_screenshot(pg_session, old_id)
    await add_screenshot(pg_session, old_id)

    listed = (await pg_client.get("/api/projects")).json()

    assert [p["name"] for p in listed] == ["Tie newer", "Tie older", "Old"]
    assert (listed[2]["transcript_count"], listed[2]["screenshot_count"]) == (1, 2)


async def test_touch_project_moves_project_to_top_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    older = await _create(pg_client, "Older")
    newer = await _create(pg_client, "Newer")
    await set_timestamps(pg_session, older["id"], created_at=at(1), updated_at=at(1))
    await set_timestamps(pg_session, newer["id"], created_at=at(2), updated_at=at(2))

    await project_service.touch_project(pg_session, uuid.UUID(older["id"]))
    await pg_session.commit()

    names = [p["name"] for p in (await pg_client.get("/api/projects")).json()]
    assert names == ["Older", "Newer"]


async def test_get_project_detail_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    created = await _create(pg_client, "Detail")
    project_id = uuid.UUID(created["id"])
    await add_transcript(pg_session, project_id, title="Old", created_at=at(1))
    await add_transcript(pg_session, project_id, title="New", created_at=at(5))
    shot = await add_screenshot(pg_session, project_id)

    body = (await pg_client.get(f"/api/projects/{project_id}")).json()

    assert [t["title"] for t in body["transcripts"]] == ["New", "Old"]
    assert all("text" not in t for t in body["transcripts"])
    assert body["screenshots"][0]["image_url"] == f"/api/screenshots/{shot.id}/image"
    assert (body["transcript_count"], body["screenshot_count"]) == (2, 1)
