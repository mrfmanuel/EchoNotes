"""#14 screenshots API (US-12, US-14, US-15) on SQLite, grouped by acceptance criterion."""

import uuid
from datetime import datetime

import httpx2
import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Screenshot
from tests.image_utils import (
    GIF,
    JPEG,
    MAX_IMAGE_BYTES,
    PNG,
    TEXT,
    WEBP,
    create_project,
    png_of_size,
    upload,
)
from tests.log_utils import parse_json_logs
from tests.project_utils import add_transcript, at, set_timestamps

pytestmark = pytest.mark.anyio

SCREENSHOT_KEYS = {
    "id",
    "project_id",
    "transcript_id",
    "filename",
    "content_type",
    "size_bytes",
    "image_url",
    "created_at",
}
SCREENSHOT_NOT_FOUND = {"detail": "Screenshot not found", "code": "not_found"}
PROJECT_NOT_FOUND = {"detail": "Project not found", "code": "not_found"}


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(Screenshot.id)))).scalar_one()


async def _updated_at(session: AsyncSession, project_id: str) -> datetime:
    session.expire_all()
    project = await session.get(Project, uuid.UUID(project_id))
    assert project is not None
    return project.updated_at


async def _uploaded(client: httpx2.AsyncClient, project_id: str, **kwargs: object) -> dict:
    response = await upload(client, project_id, **kwargs)  # type: ignore[arg-type]
    assert response.status_code == 201, response.text
    return response.json()


# --- AC1: upload, magic bytes, size limit ---------------------------------------------------


@pytest.mark.parametrize(
    ("data", "filename", "content_type"),
    [
        pytest.param(PNG, "a.png", "image/png", id="png"),
        pytest.param(JPEG, "b.jpg", "image/jpeg", id="jpeg"),
        pytest.param(WEBP, "c.webp", "image/webp", id="webp"),
    ],
)
async def test_upload_valid_image_returns_201_screenshot(
    client: httpx2.AsyncClient, data: bytes, filename: str, content_type: str
) -> None:
    project = await create_project(client)

    response = await upload(client, project["id"], data=data, filename=filename, mime=content_type)

    assert response.status_code == 201
    body = response.json()
    assert set(body) == SCREENSHOT_KEYS
    assert body["project_id"] == project["id"]
    assert body["transcript_id"] is None
    assert (body["filename"], body["content_type"]) == (filename, content_type)
    assert body["size_bytes"] == len(data)
    assert body["image_url"] == f"/api/screenshots/{body['id']}/image"


async def test_upload_stores_content_type_from_magic_bytes_not_from_client(
    client: httpx2.AsyncClient,
) -> None:
    project = await create_project(client)

    body = await _uploaded(client, project["id"], data=JPEG, filename="x.png", mime="text/plain")

    assert body["content_type"] == "image/jpeg"


@pytest.mark.parametrize(
    ("data", "filename", "mime"),
    [
        pytest.param(TEXT, "spoofed.png", "image/png", id="png-name-and-mime-with-text-bytes"),
        pytest.param(GIF, "anim.gif", "image/gif", id="gif"),
        pytest.param(b"", "empty.png", "image/png", id="empty-file"),
    ],
)
async def test_upload_non_image_bytes_returns_415_and_stores_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, data: bytes, filename: str, mime: str
) -> None:
    project = await create_project(client)

    response = await upload(client, project["id"], data=data, filename=filename, mime=mime)

    assert response.status_code == 415
    assert response.json() == {
        "detail": "Only png, jpeg and webp images are allowed",
        "code": "unsupported_media_type",
    }
    assert await _count(session) == 0


async def test_upload_exactly_5_mib_is_accepted(client: httpx2.AsyncClient) -> None:
    project = await create_project(client)

    body = await _uploaded(client, project["id"], data=png_of_size(MAX_IMAGE_BYTES))

    assert body["size_bytes"] == MAX_IMAGE_BYTES


async def test_upload_5_mib_plus_one_byte_returns_413_and_stores_nothing(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client)

    response = await upload(client, project["id"], data=png_of_size(MAX_IMAGE_BYTES + 1))

    assert response.status_code == 413
    assert response.json() == {"detail": "Image exceeds the 5 MB limit", "code": "image_too_large"}
    assert await _count(session) == 0


async def test_upload_limit_follows_max_image_mb_setting(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = await create_project(client)
    monkeypatch.setenv("MAX_IMAGE_MB", "1")
    from app.config import get_settings

    get_settings.cache_clear()

    response = await upload(client, project["id"], data=png_of_size(1024 * 1024 + 1))

    assert response.status_code == 413


async def test_upload_without_file_returns_422(client: httpx2.AsyncClient) -> None:
    project = await create_project(client)

    response = await client.post(f"/api/projects/{project['id']}/screenshots", data={"x": "1"})

    assert response.status_code == 422


# --- AC2: optional transcript_id, unknown project -------------------------------------------


async def test_upload_with_transcript_of_same_project_links_it(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client)
    transcript = await add_transcript(session, uuid.UUID(project["id"]))

    body = await _uploaded(client, project["id"], transcript_id=str(transcript.id))

    assert body["transcript_id"] == str(transcript.id)


@pytest.mark.parametrize("owner", ["other-project", "unknown-id"])
async def test_upload_with_transcript_of_other_project_or_unknown_returns_422(
    client: httpx2.AsyncClient, session: AsyncSession, owner: str
) -> None:
    project = await create_project(client, "Mine")
    other = await create_project(client, "Other")
    transcript_id = (
        str((await add_transcript(session, uuid.UUID(other["id"]))).id)
        if owner == "other-project"
        else str(uuid.uuid4())
    )

    response = await upload(client, project["id"], transcript_id=transcript_id)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert await _count(session) == 0


async def test_upload_with_malformed_transcript_id_returns_422(
    client: httpx2.AsyncClient,
) -> None:
    project = await create_project(client)

    response = await upload(client, project["id"], transcript_id="not-a-uuid")

    assert response.status_code == 422


async def test_upload_to_unknown_project_returns_404(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    response = await upload(client, str(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json() == PROJECT_NOT_FOUND
    assert await _count(session) == 0


# --- AC3: PATCH link / unlink, image endpoint -----------------------------------------------


async def test_patch_links_and_unlinks_a_transcript(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client)
    transcript = await add_transcript(session, uuid.UUID(project["id"]))
    shot = await _uploaded(client, project["id"])

    linked = await client.patch(
        f"/api/screenshots/{shot['id']}", json={"transcript_id": str(transcript.id)}
    )
    assert linked.status_code == 200
    assert linked.json()["transcript_id"] == str(transcript.id)

    unlinked = await client.patch(f"/api/screenshots/{shot['id']}", json={"transcript_id": None})
    assert unlinked.status_code == 200
    assert unlinked.json()["transcript_id"] is None
    session.expire_all()
    stored = await session.get(Screenshot, uuid.UUID(shot["id"]))
    assert stored is not None and stored.transcript_id is None


@pytest.mark.parametrize("owner", ["other-project", "unknown-id"])
async def test_patch_with_transcript_of_other_project_or_unknown_returns_422(
    client: httpx2.AsyncClient, session: AsyncSession, owner: str
) -> None:
    project = await create_project(client, "Mine")
    other = await create_project(client, "Other")
    shot = await _uploaded(client, project["id"])
    transcript_id = (
        str((await add_transcript(session, uuid.UUID(other["id"]))).id)
        if owner == "other-project"
        else str(uuid.uuid4())
    )

    response = await client.patch(
        f"/api/screenshots/{shot['id']}", json={"transcript_id": transcript_id}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_patch_with_empty_body_changes_nothing(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client)
    transcript = await add_transcript(session, uuid.UUID(project["id"]))
    shot = await _uploaded(client, project["id"], transcript_id=str(transcript.id))

    response = await client.patch(f"/api/screenshots/{shot['id']}", json={})

    assert response.status_code == 200
    assert response.json()["transcript_id"] == str(transcript.id)


async def test_patch_unknown_screenshot_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.patch(f"/api/screenshots/{uuid.uuid4()}", json={"transcript_id": None})

    assert response.status_code == 404
    assert response.json() == SCREENSHOT_NOT_FOUND


@pytest.mark.parametrize(
    ("data", "content_type"),
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")],
)
async def test_get_image_returns_bytes_content_type_and_cache_control(
    client: httpx2.AsyncClient, data: bytes, content_type: str
) -> None:
    project = await create_project(client)
    shot = await _uploaded(client, project["id"], data=data, mime="application/octet-stream")

    response = await client.get(shot["image_url"])

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == content_type
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"


async def test_get_image_of_unknown_screenshot_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"/api/screenshots/{uuid.uuid4()}/image")

    assert response.status_code == 404
    assert response.json() == SCREENSHOT_NOT_FOUND


# --- AC4: delete ----------------------------------------------------------------------------


async def test_delete_screenshot_returns_204_and_removes_it(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client)
    shot = await _uploaded(client, project["id"])

    response = await client.delete(f"/api/screenshots/{shot['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert await _count(session) == 0
    assert (await client.get(shot["image_url"])).status_code == 404
    assert (await client.get(f"/api/projects/{project['id']}/screenshots")).json() == []


async def test_delete_unknown_screenshot_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.delete(f"/api/screenshots/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == SCREENSHOT_NOT_FOUND


# --- AC5: list metadata only, oldest first --------------------------------------------------


async def test_list_returns_metadata_oldest_first(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client)
    second = await _uploaded(client, project["id"], filename="second.png")
    first = await _uploaded(client, project["id"], filename="first.png")
    for shot_id, minute in ((second["id"], 2), (first["id"], 1)):
        stored = await session.get(Screenshot, uuid.UUID(shot_id))
        assert stored is not None
        stored.created_at = at(minute)
    await session.commit()

    response = await client.get(f"/api/projects/{project['id']}/screenshots")

    assert response.status_code == 200
    body = response.json()
    assert [s["filename"] for s in body] == ["first.png", "second.png"]
    assert all(set(s) == SCREENSHOT_KEYS for s in body)
    assert all(s["image_url"] == f"/api/screenshots/{s['id']}/image" for s in body)


async def test_list_does_not_load_image_bytes(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    from app.services import screenshots as service

    project = await create_project(client)
    await _uploaded(client, project["id"])
    session.expire_all()

    listed = await service.list_screenshots(session, uuid.UUID(project["id"]))

    assert len(listed) == 1
    assert "data" in inspect(listed[0]).unloaded


async def test_list_unknown_project_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"/api/projects/{uuid.uuid4()}/screenshots")

    assert response.status_code == 404
    assert response.json() == PROJECT_NOT_FOUND


# --- AC6: project updated_at bump (US-02 AC3) -----------------------------------------------


async def test_upload_patch_and_delete_bump_project_updated_at(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client)
    transcript_id = str((await add_transcript(session, uuid.UUID(project["id"]))).id)
    await set_timestamps(session, project["id"], at(0), at(0))

    shot = await _uploaded(client, project["id"])
    after_upload = await _updated_at(session, project["id"])
    assert after_upload > at(0)

    await client.patch(f"/api/screenshots/{shot['id']}", json={"transcript_id": transcript_id})
    after_patch = await _updated_at(session, project["id"])
    assert after_patch > after_upload

    await client.delete(f"/api/screenshots/{shot['id']}")
    assert await _updated_at(session, project["id"]) > after_patch


async def test_rejected_upload_does_not_bump_project_updated_at(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client)
    await set_timestamps(session, project["id"], at(0), at(0))

    await upload(client, project["id"], data=TEXT)

    assert await _updated_at(session, project["id"]) == at(0)


# --- AC7: privacy in logs -------------------------------------------------------------------


async def test_upload_logs_ids_and_size_but_never_filename_or_bytes(
    client: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    project = await create_project(client)
    capsys.readouterr()
    marker = b"\x89PNG\r\n\x1a\nSECRET-PIXELS"

    shot = await _uploaded(client, project["id"], data=marker, filename="Confidential-Plan.png")
    await client.patch(f"/api/screenshots/{shot['id']}", json={"transcript_id": None})
    await client.get(shot["image_url"])
    await client.delete(f"/api/screenshots/{shot['id']}")

    output = capsys.readouterr().out
    assert "Confidential" not in output
    assert "SECRET-PIXELS" not in output
    uploaded = [r for r in parse_json_logs(output) if r.get("message") == "screenshot uploaded"]
    assert len(uploaded) == 1
    assert uploaded[0]["screenshot_id"] == shot["id"]
    assert uploaded[0]["size_bytes"] == len(marker)
