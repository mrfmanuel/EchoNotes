"""#13 list/get/edit/delete/download transcripts (US-08, US-10, US-11, US-02 AC3) on SQLite."""

import uuid
from datetime import datetime
from typing import Any

import httpx2
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TRANSCRIPT_TITLE_MAX, Screenshot, Transcript
from app.services.transcript_format import render_markdown, render_text
from tests.log_utils import parse_json_logs
from tests.project_utils import add_screenshot, add_transcript, at, set_timestamps
from tests.transcription_utils import upload

pytestmark = pytest.mark.anyio

SUMMARY_KEYS = {
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
TRANSCRIPT_KEYS = SUMMARY_KEYS | {"text", "source_filename"}
MISSING_ID = "00000000-0000-4000-8000-000000000000"


async def _project(client: httpx2.AsyncClient, name: str = "Lectures") -> str:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


async def _transcript(client: httpx2.AsyncClient, project_id: str, **form: str) -> dict[str, Any]:
    response = await upload(client, project_id, "Clase 1.m4a", **form)
    assert response.status_code == 201, response.text
    return response.json()


async def _age(session: AsyncSession, project_id: str, transcript_id: str) -> None:
    """Move the project's and transcript's timestamps into the past (minute 1)."""
    await set_timestamps(session, project_id, created_at=at(1), updated_at=at(1))
    await session.execute(
        update(Transcript)
        .where(Transcript.id == uuid.UUID(transcript_id))
        .values(created_at=at(1), updated_at=at(1))
    )
    await session.commit()


async def _project_updated_at(client: httpx2.AsyncClient, project_id: str) -> datetime:
    return datetime.fromisoformat(
        (await client.get(f"/api/projects/{project_id}")).json()["updated_at"]
    )


def _assert_not_found(response: httpx2.Response) -> None:
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --- GET /api/transcriptions/{id} (US-08) ----------------------------------------------------


async def test_get_transcript_returns_full_transcript(client: httpx2.AsyncClient) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    response = await client.get(f"/api/transcriptions/{created['id']}")

    assert response.status_code == 200
    assert set(response.json()) == TRANSCRIPT_KEYS
    assert response.json() == created


async def test_get_unknown_transcript_returns_404_not_found(client: httpx2.AsyncClient) -> None:
    _assert_not_found(await client.get(f"/api/transcriptions/{MISSING_ID}"))


async def test_get_transcript_with_malformed_id_returns_422(client: httpx2.AsyncClient) -> None:
    assert (await client.get("/api/transcriptions/not-a-uuid")).status_code == 422


# --- GET /api/projects/{id}/transcriptions (listTranscriptions) ------------------------------


async def test_list_transcriptions_returns_summaries_newest_first(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project_id = uuid.UUID(await _project(client))
    old = await add_transcript(session, project_id, "Old", created_at=at(1))
    new = await add_transcript(session, project_id, "New", created_at=at(3))
    middle = await add_transcript(session, project_id, "Middle", created_at=at(2))
    other_project = uuid.UUID(await _project(client, "Other"))
    await add_transcript(session, other_project, "Elsewhere")

    response = await client.get(f"/api/projects/{project_id}/transcriptions")

    assert response.status_code == 200
    body = response.json()
    assert [t["id"] for t in body] == [str(new.id), str(middle.id), str(old.id)]
    assert all(set(t) == SUMMARY_KEYS for t in body)  # no `text`


async def test_list_transcriptions_of_empty_project_is_empty(client: httpx2.AsyncClient) -> None:
    project_id = await _project(client)

    response = await client.get(f"/api/projects/{project_id}/transcriptions")

    assert (response.status_code, response.json()) == (200, [])


async def test_list_transcriptions_of_unknown_project_returns_404(
    client: httpx2.AsyncClient,
) -> None:
    _assert_not_found(await client.get(f"/api/projects/{MISSING_ID}/transcriptions"))


# --- PATCH /api/transcriptions/{id} (US-08, US-10 AC5, US-02 AC3) ----------------------------


async def test_patch_title_is_trimmed_and_recomputes_slug(client: httpx2.AsyncClient) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    response = await client.patch(
        f"/api/transcriptions/{created['id']}", json={"title": "  Física: Clase 2  "}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["title"], body["slug"]) == ("Física: Clase 2", "fisica-clase-2")
    assert body["text"] == created["text"]


async def test_patch_title_without_slug_characters_falls_back_to_transcript_slug(
    client: httpx2.AsyncClient,
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    response = await client.patch(f"/api/transcriptions/{created['id']}", json={"title": "¿?"})

    assert response.json()["slug"] == "transcript"


async def test_patch_text_only_keeps_title_and_slug(client: httpx2.AsyncClient) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    response = await client.patch(
        f"/api/transcriptions/{created['id']}", json={"text": "Edited text.\nLine 2"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Edited text.\nLine 2"
    assert (body["title"], body["slug"]) == (created["title"], created["slug"])


async def test_patch_text_may_be_empty(client: httpx2.AsyncClient) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    response = await client.patch(f"/api/transcriptions/{created['id']}", json={"text": ""})

    assert (response.status_code, response.json()["text"]) == (200, "")


async def test_patch_edit_persists_after_refetch(client: httpx2.AsyncClient) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    await client.patch(
        f"/api/transcriptions/{created['id']}", json={"title": "Renamed", "text": "New text"}
    )
    body = (await client.get(f"/api/transcriptions/{created['id']}")).json()

    assert (body["title"], body["slug"], body["text"]) == ("Renamed", "renamed", "New text")


async def test_patch_bumps_transcript_and_project_updated_at(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)
    await _age(session, project_id, created["id"])

    response = await client.patch(f"/api/transcriptions/{created['id']}", json={"text": "x"})

    body = response.json()
    assert datetime.fromisoformat(body["updated_at"]) > at(1)
    assert datetime.fromisoformat(body["created_at"]) == at(1)
    assert await _project_updated_at(client, project_id) > at(1)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * (TRANSCRIPT_TITLE_MAX + 1)},
        {"title": None},
        {"text": None},
        {"title": 5},
    ],
    ids=[
        "empty-body",
        "empty-title",
        "blank-title",
        "title-too-long",
        "null-title",
        "null-text",
        "non-string-title",
    ],
)
async def test_patch_rejects_invalid_body_with_422(
    client: httpx2.AsyncClient, payload: dict[str, Any]
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    response = await client.patch(f"/api/transcriptions/{created['id']}", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    unchanged = (await client.get(f"/api/transcriptions/{created['id']}")).json()
    assert unchanged == created


async def test_patch_accepts_title_of_max_length(client: httpx2.AsyncClient) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)
    title = "a" * TRANSCRIPT_TITLE_MAX

    response = await client.patch(f"/api/transcriptions/{created['id']}", json={"title": title})

    assert (response.status_code, response.json()["title"]) == (200, title)


async def test_patch_unknown_transcript_returns_404(client: httpx2.AsyncClient) -> None:
    _assert_not_found(await client.patch(f"/api/transcriptions/{MISSING_ID}", json={"text": "x"}))


# --- DELETE /api/transcriptions/{id} (US-11, US-02 AC3) --------------------------------------


async def test_delete_returns_204_and_transcript_is_gone(client: httpx2.AsyncClient) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    response = await client.delete(f"/api/transcriptions/{created['id']}")

    assert (response.status_code, response.content) == (204, b"")
    _assert_not_found(await client.get(f"/api/transcriptions/{created['id']}"))
    assert (await client.get(f"/api/projects/{project_id}/transcriptions")).json() == []


async def test_delete_keeps_linked_screenshots_and_clears_their_link(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)
    linked_id = (await add_screenshot(session, uuid.UUID(project_id), uuid.UUID(created["id"]))).id

    await client.delete(f"/api/transcriptions/{created['id']}")

    session.expire_all()
    screenshot = await session.get(Screenshot, linked_id)
    assert screenshot is not None and screenshot.transcript_id is None
    listed = (await client.get(f"/api/projects/{project_id}/screenshots")).json()
    assert [(s["id"], s["transcript_id"]) for s in listed] == [(str(linked_id), None)]


async def test_delete_bumps_project_updated_at(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)
    await _age(session, project_id, created["id"])

    await client.delete(f"/api/transcriptions/{created['id']}")

    assert await _project_updated_at(client, project_id) > at(1)


async def test_delete_unknown_transcript_returns_404(client: httpx2.AsyncClient) -> None:
    _assert_not_found(await client.delete(f"/api/transcriptions/{MISSING_ID}"))


# --- GET /api/transcriptions/{id}/download (US-10) -------------------------------------------


async def test_download_md_body_equals_render_markdown_with_headers(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id, title="Física 1", language="es")

    response = await client.get(f"/api/transcriptions/{created['id']}/download?format=md")

    assert response.status_code == 200
    stored = await session.get(Transcript, uuid.UUID(created["id"]))
    assert stored is not None
    assert response.content == render_markdown(stored).encode("utf-8")
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="fisica-1.md"'


async def test_download_md_has_heading_metadata_line_blank_line_and_text(
    client: httpx2.AsyncClient,
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id, title="Física 1", language="es")
    date = created["created_at"][:10]

    response = await client.get(f"/api/transcriptions/{created['id']}/download?format=md")

    lines = response.content.decode("utf-8").split("\n")
    assert lines[0] == "# Física 1"
    assert lines[1] == f"Date: {date} · Language: es · Duration: 0:02"
    assert lines[2] == ""
    assert lines[3] == created["text"]


async def test_download_txt_is_plain_text_only_with_headers(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id, title="Notes")

    response = await client.get(f"/api/transcriptions/{created['id']}/download?format=txt")

    assert response.status_code == 200
    stored = await session.get(Transcript, uuid.UUID(created["id"]))
    assert stored is not None
    assert response.content == render_text(stored).encode("utf-8") == created["text"].encode()
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="notes.txt"'


async def test_download_filename_follows_slug_after_title_edit(
    client: httpx2.AsyncClient,
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id, title="Old name")
    await client.patch(f"/api/transcriptions/{created['id']}", json={"title": "New name"})

    response = await client.get(f"/api/transcriptions/{created['id']}/download?format=md")

    assert response.headers["content-disposition"] == 'attachment; filename="new-name.md"'
    assert response.content.decode("utf-8").startswith("# New name\n")


@pytest.mark.parametrize("query", ["", "?format=pdf", "?format=MD", "?format="])
async def test_download_with_missing_or_invalid_format_returns_422(
    client: httpx2.AsyncClient, query: str
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)

    response = await client.get(f"/api/transcriptions/{created['id']}/download{query}")

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


async def test_download_unknown_transcript_returns_404(client: httpx2.AsyncClient) -> None:
    _assert_not_found(await client.get(f"/api/transcriptions/{MISSING_ID}/download?format=txt"))


# --- Privacy: logs carry IDs only -----------------------------------------------------------


async def test_edit_download_delete_never_log_title_or_text(
    client: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    project_id = await _project(client)
    created = await _transcript(client, project_id)
    capsys.readouterr()

    await client.patch(
        f"/api/transcriptions/{created['id']}",
        json={"title": "Secret Title Zeta", "text": "secret body omega"},
    )
    await client.get(f"/api/transcriptions/{created['id']}/download?format=md")
    await client.delete(f"/api/transcriptions/{created['id']}")

    output = capsys.readouterr().out
    assert "Secret Title Zeta" not in output and "secret body omega" not in output
    assert "secret-title-zeta" not in output
    messages = {r["message"] for r in parse_json_logs(output)}
    assert {"transcript updated", "transcript downloaded", "transcript deleted"} <= messages
