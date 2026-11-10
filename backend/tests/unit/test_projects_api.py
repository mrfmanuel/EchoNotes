"""#10 projects API (US-01..US-04) on SQLite, one test (or more) per acceptance criterion."""

import re
import uuid
from datetime import datetime
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Project, Screenshot, Transcript
from app.errors import NotFoundError
from app.services import projects as project_service
from tests.log_utils import parse_json_logs
from tests.project_utils import add_screenshot, add_transcript, at, set_timestamps

pytestmark = pytest.mark.anyio

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROJECT_KEYS = {
    "id",
    "name",
    "slug",
    "transcript_count",
    "screenshot_count",
    "created_at",
    "updated_at",
}
NOT_FOUND_BODY = {"detail": "Project not found", "code": "not_found"}
INVALID_NAMES = [
    pytest.param({"name": ""}, id="blank"),
    pytest.param({"name": "   \t\n "}, id="whitespace-only"),
    pytest.param({"name": "x" * 101}, id="too-long"),
    pytest.param({}, id="missing"),
    pytest.param({"name": None}, id="null"),
    pytest.param({"name": 42}, id="not-a-string"),
]


async def _create(client: httpx2.AsyncClient, name: str) -> dict[str, Any]:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def _project_rows(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(Project.id)))).scalar_one()


# --- Create (US-01) -------------------------------------------------------------------------


async def test_create_project_returns_201_with_project_body_and_zero_counts(
    client: httpx2.AsyncClient,
) -> None:
    response = await client.post("/api/projects", json={"name": "Lecture notes"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == PROJECT_KEYS
    assert uuid.UUID(body["id"])
    assert body["name"] == "Lecture notes"
    assert body["slug"] == "lecture-notes"
    assert (body["transcript_count"], body["screenshot_count"]) == (0, 0)
    created_at = datetime.fromisoformat(body["created_at"])
    assert created_at.tzinfo is not None
    assert datetime.fromisoformat(body["updated_at"]) >= created_at


async def test_create_project_strips_whitespace_from_name(client: httpx2.AsyncClient) -> None:
    body = await _create(client, "   Physics 101  ")

    assert body["name"] == "Physics 101"
    listed = (await client.get("/api/projects")).json()
    assert listed[0]["name"] == "Physics 101"


async def test_create_project_measures_length_after_stripping(
    client: httpx2.AsyncClient,
) -> None:
    body = await _create(client, "  " + "a" * 100 + "  ")

    assert body["name"] == "a" * 100


@pytest.mark.parametrize("payload", INVALID_NAMES)
async def test_create_project_rejects_invalid_name_with_422_and_creates_no_row(
    client: httpx2.AsyncClient, session: AsyncSession, payload: dict[str, Any]
) -> None:
    response = await client.post("/api/projects", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert await _project_rows(session) == 0


async def test_create_project_slug_transliterates_accents(client: httpx2.AsyncClient) -> None:
    body = await _create(client, "Clase de Física")

    assert body["slug"] == "clase-de-fisica"


async def test_create_project_slug_falls_back_to_project(client: httpx2.AsyncClient) -> None:
    body = await _create(client, "!!!")

    assert body["slug"] == "project"


async def test_create_project_adds_suffix_on_slug_collision(client: httpx2.AsyncClient) -> None:
    first = await _create(client, "Notes")
    second = await _create(client, "notes")

    assert (first["slug"], second["slug"]) == ("notes", "notes-2")


async def test_create_project_slug_is_notes_3_when_notes_and_notes_2_exist(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    session.add_all([Project(name="A", slug="notes"), Project(name="B", slug="notes-2")])
    await session.commit()

    body = await _create(client, "Notes")

    assert body["slug"] == "notes-3"
    assert SLUG_PATTERN.match(body["slug"])


async def test_create_project_retries_when_a_concurrent_insert_took_the_slug(
    client: httpx2.AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.add(Project(name="Notes", slug="notes"))
    await session.commit()
    real_unique_slug = project_service.unique_slug
    calls: list[str] = []

    async def stale_then_real(*args: Any, **kwargs: Any) -> str:
        calls.append("call")
        if len(calls) == 1:
            return "notes"  # what a racing request would have computed before our commit
        return await real_unique_slug(*args, **kwargs)

    monkeypatch.setattr(project_service, "unique_slug", stale_then_real)

    body = await _create(client, "Notes")

    assert body["slug"] == "notes-2"
    assert len(calls) == 2
    assert await _project_rows(session) == 2


async def test_create_project_does_not_log_the_name(
    client: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await _create(client, "Confidential Merger Plan")

    output = capsys.readouterr().out
    assert "Confidential" not in output
    assert any(r.get("message") == "project created" for r in parse_json_logs(output))


# --- List (US-02) ---------------------------------------------------------------------------


async def test_list_projects_returns_empty_list_for_empty_db(client: httpx2.AsyncClient) -> None:
    response = await client.get("/api/projects")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_projects_sorted_by_updated_at_desc(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    old = await _create(client, "Old")
    new = await _create(client, "New")
    middle = await _create(client, "Middle")
    await set_timestamps(session, old["id"], created_at=at(1), updated_at=at(2))
    await set_timestamps(session, new["id"], created_at=at(1), updated_at=at(9))
    await set_timestamps(session, middle["id"], created_at=at(1), updated_at=at(5))

    names = [p["name"] for p in (await client.get("/api/projects")).json()]

    assert names == ["New", "Middle", "Old"]


async def test_list_projects_breaks_updated_at_ties_by_created_at_desc(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    first = await _create(client, "First")
    second = await _create(client, "Second")
    await set_timestamps(session, first["id"], created_at=at(3), updated_at=at(10))
    await set_timestamps(session, second["id"], created_at=at(1), updated_at=at(10))

    names = [p["name"] for p in (await client.get("/api/projects")).json()]

    assert names == ["First", "Second"]


async def test_list_projects_reports_transcript_and_screenshot_counts(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    busy = await _create(client, "Busy")
    empty = await _create(client, "Empty")
    busy_id = uuid.UUID(busy["id"])
    transcript = await add_transcript(session, busy_id)
    await add_transcript(session, busy_id, title="Second")
    await add_screenshot(session, busy_id, transcript.id)
    await add_screenshot(session, busy_id)
    await add_screenshot(session, busy_id)

    listed = {p["name"]: p for p in (await client.get("/api/projects")).json()}

    assert (listed["Busy"]["transcript_count"], listed["Busy"]["screenshot_count"]) == (2, 3)
    assert (listed["Empty"]["transcript_count"], listed["Empty"]["screenshot_count"]) == (0, 0)
    assert set(listed[empty["name"]]) == PROJECT_KEYS


async def test_list_projects_rename_moves_project_to_top(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    older = await _create(client, "Older")
    newer = await _create(client, "Newer")
    await set_timestamps(session, older["id"], created_at=at(1), updated_at=at(1))
    await set_timestamps(session, newer["id"], created_at=at(2), updated_at=at(2))

    await client.patch(f"/api/projects/{older['id']}", json={"name": "Older renamed"})
    names = [p["name"] for p in (await client.get("/api/projects")).json()]

    assert names == ["Older renamed", "Newer"]


# --- US-02 AC3: shared updated_at bump for transcripts/screenshots (#12/#13/#14) ------------


async def test_touch_project_bumps_updated_at_and_moves_project_to_top_of_list(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    older = await _create(client, "Older")
    newer = await _create(client, "Newer")
    await set_timestamps(session, older["id"], created_at=at(1), updated_at=at(1))
    await set_timestamps(session, newer["id"], created_at=at(2), updated_at=at(2))

    await project_service.touch_project(session, uuid.UUID(older["id"]))
    await session.commit()
    listed = (await client.get("/api/projects")).json()

    assert [p["name"] for p in listed] == ["Older", "Newer"]
    assert datetime.fromisoformat(listed[0]["updated_at"]) > at(2)


async def test_touch_project_unknown_id_raises_not_found(session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await project_service.touch_project(session, uuid.uuid4())


async def test_bump_updated_at_is_strictly_increasing_with_a_coarse_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_service, "utcnow", lambda: at(5))
    project = Project(name="P", slug="p", updated_at=at(5))

    project_service.bump_updated_at(project)

    assert project.updated_at > at(5)


# --- Get one --------------------------------------------------------------------------------


async def test_get_project_returns_detail_with_empty_lists(client: httpx2.AsyncClient) -> None:
    created = await _create(client, "Empty")

    response = await client.get(f"/api/projects/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == PROJECT_KEYS | {"transcripts", "screenshots"}
    assert body["transcripts"] == [] and body["screenshots"] == []
    assert {k: body[k] for k in PROJECT_KEYS} == created


async def test_get_project_lists_transcript_summaries_newest_first_without_text(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    created = await _create(client, "Lectures")
    project_id = uuid.UUID(created["id"])
    await add_transcript(session, project_id, title="Old", created_at=at(1))
    await add_transcript(session, project_id, title="New", created_at=at(9))

    body = (await client.get(f"/api/projects/{project_id}")).json()

    assert [t["title"] for t in body["transcripts"]] == ["New", "Old"]
    summary = body["transcripts"][0]
    assert set(summary) == {
        "id",
        "project_id",
        "title",
        "slug",
        "language",
        "duration_seconds",
        "provider",
        "created_at",
        "updated_at",
    }
    assert summary["project_id"] == created["id"]
    assert (summary["language"], summary["provider"]) == ("es", "fake")
    assert body["transcript_count"] == 2


async def test_get_project_lists_screenshot_metadata_with_image_url_and_no_bytes(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    created = await _create(client, "Slides")
    project_id = uuid.UUID(created["id"])
    transcript = await add_transcript(session, project_id)
    old = await add_screenshot(session, project_id, transcript.id, created_at=at(1))
    new = await add_screenshot(session, project_id, created_at=at(9))

    body = (await client.get(f"/api/projects/{project_id}")).json()

    assert [s["id"] for s in body["screenshots"]] == [str(old.id), str(new.id)]
    shot = body["screenshots"][0]
    assert set(shot) == {
        "id",
        "project_id",
        "transcript_id",
        "filename",
        "content_type",
        "size_bytes",
        "image_url",
        "created_at",
    }
    assert shot["image_url"] == f"/api/screenshots/{old.id}/image"
    assert shot["transcript_id"] == str(transcript.id)
    assert (shot["content_type"], shot["size_bytes"]) == ("image/png", old.size_bytes)
    assert body["screenshots"][1]["transcript_id"] is None


async def test_get_project_embeds_screenshots_oldest_first_like_the_screenshots_list(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    created = await _create(client, "Ordered")
    project_id = uuid.UUID(created["id"])
    middle = await add_screenshot(session, project_id, created_at=at(5))
    newest = await add_screenshot(session, project_id, created_at=at(9))
    oldest = await add_screenshot(session, project_id, created_at=at(1))

    detail = (await client.get(f"/api/projects/{project_id}")).json()
    listed = (await client.get(f"/api/projects/{project_id}/screenshots")).json()

    expected = [str(oldest.id), str(middle.id), str(newest.id)]
    assert [s["id"] for s in detail["screenshots"]] == expected
    assert [s["id"] for s in listed] == expected


async def test_get_project_contents_does_not_load_screenshot_bytes_or_transcript_text(
    session: AsyncSession, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    project = Project(name="P", slug="p")
    session.add(project)
    await session.commit()
    await add_transcript(session, project.id)
    await add_screenshot(session, project.id)

    async with session_maker() as fresh:
        contents = await project_service.get_project_contents(fresh, project.id)

    assert "data" in inspect(contents.screenshots[0]).unloaded
    assert "text" in inspect(contents.transcripts[0]).unloaded


async def test_get_project_unknown_id_returns_404_error_body(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"/api/projects/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY


# --- Rename (US-03) -------------------------------------------------------------------------


async def test_rename_project_keeps_slug_and_increases_updated_at(
    client: httpx2.AsyncClient,
) -> None:
    created = await _create(client, "Draft")

    response = await client.patch(f"/api/projects/{created['id']}", json={"name": "  Final  "})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == PROJECT_KEYS
    assert body["name"] == "Final"
    assert body["slug"] == "draft"
    assert body["created_at"] == created["created_at"]
    assert datetime.fromisoformat(body["updated_at"]) > datetime.fromisoformat(
        created["updated_at"]
    )
    detail = (await client.get(f"/api/projects/{created['id']}")).json()
    assert (detail["name"], detail["slug"]) == ("Final", "draft")


async def test_rename_project_returns_current_counts(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    created = await _create(client, "Counted")
    await add_transcript(session, uuid.UUID(created["id"]))

    body = (await client.patch(f"/api/projects/{created['id']}", json={"name": "C"})).json()

    assert (body["transcript_count"], body["screenshot_count"]) == (1, 0)


@pytest.mark.parametrize("payload", INVALID_NAMES)
async def test_rename_project_rejects_invalid_name_with_422(
    client: httpx2.AsyncClient, payload: dict[str, Any]
) -> None:
    created = await _create(client, "Keep me")

    response = await client.patch(f"/api/projects/{created['id']}", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    detail = (await client.get(f"/api/projects/{created['id']}")).json()
    assert (detail["name"], detail["updated_at"]) == ("Keep me", created["updated_at"])


async def test_rename_project_unknown_id_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.patch(f"/api/projects/{uuid.uuid4()}", json={"name": "X"})

    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY


# --- Delete (US-04) -------------------------------------------------------------------------


async def test_delete_project_returns_204_and_cascades_transcripts_and_screenshots(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    doomed = await _create(client, "Doomed")
    kept = await _create(client, "Kept")
    doomed_id, kept_id = uuid.UUID(doomed["id"]), uuid.UUID(kept["id"])
    transcript = await add_transcript(session, doomed_id)
    await add_screenshot(session, doomed_id, transcript.id)
    await add_transcript(session, kept_id)
    await add_screenshot(session, kept_id)

    response = await client.delete(f"/api/projects/{doomed_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert (await client.get(f"/api/projects/{doomed_id}")).status_code == 404
    project_ids = {
        "transcripts": set((await session.scalars(select(Transcript.project_id))).all()),
        "screenshots": set((await session.scalars(select(Screenshot.project_id))).all()),
    }
    assert project_ids == {"transcripts": {kept_id}, "screenshots": {kept_id}}
    assert [p["name"] for p in (await client.get("/api/projects")).json()] == ["Kept"]


async def test_delete_project_twice_returns_404_the_second_time(
    client: httpx2.AsyncClient,
) -> None:
    created = await _create(client, "Once")

    first = await client.delete(f"/api/projects/{created['id']}")
    second = await client.delete(f"/api/projects/{created['id']}")

    assert first.status_code == 204
    assert second.status_code == 404
    assert second.json() == NOT_FOUND_BODY


async def test_delete_project_unknown_id_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.delete(f"/api/projects/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == NOT_FOUND_BODY


# --- Errors ---------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
async def test_non_uuid_project_id_returns_422(client: httpx2.AsyncClient, method: str) -> None:
    response = await client.request(method, "/api/projects/not-a-uuid", json={"name": "X"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
