"""#14 / #15 on a real Postgres: screenshot flows (bytea), export ZIP tree, cascade, set-null."""

import uuid

import httpx2
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Screenshot, Transcript
from app.services.transcript_format import render_markdown, render_text
from tests.image_utils import (
    JPEG,
    MAX_IMAGE_BYTES,
    PNG,
    TEXT,
    WEBP,
    create_project,
    png_of_size,
    unzip,
    upload,
)
from tests.project_utils import add_transcript, at

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def _count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(Screenshot.id)))).scalar_one()


async def test_screenshot_upload_list_image_link_delete_flow_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project = await create_project(pg_client, "Física")
    transcript_id = str((await add_transcript(pg_session, uuid.UUID(project["id"]))).id)

    created = await upload(pg_client, project["id"], data=WEBP, filename="a.png", mime="image/png")
    assert created.status_code == 201, created.text
    shot = created.json()
    assert shot["content_type"] == "image/webp"

    listed = (await pg_client.get(f"/api/projects/{project['id']}/screenshots")).json()
    assert [s["id"] for s in listed] == [shot["id"]]

    image = await pg_client.get(shot["image_url"])
    assert (image.content, image.headers["content-type"]) == (WEBP, "image/webp")
    assert image.headers["cache-control"] == "private, max-age=31536000, immutable"

    linked = await pg_client.patch(
        f"/api/screenshots/{shot['id']}", json={"transcript_id": transcript_id}
    )
    assert linked.json()["transcript_id"] == transcript_id
    unlinked = await pg_client.patch(f"/api/screenshots/{shot['id']}", json={"transcript_id": None})
    assert unlinked.json()["transcript_id"] is None

    assert (await pg_client.delete(f"/api/screenshots/{shot['id']}")).status_code == 204
    again = await pg_client.delete(f"/api/screenshots/{shot['id']}")
    assert again.json() == {"detail": "Screenshot not found", "code": "not_found"}
    assert await _count(pg_session) == 0


async def test_rejected_uploads_store_nothing_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project = await create_project(pg_client)
    other = await create_project(pg_client, "Other")
    foreign = str((await add_transcript(pg_session, uuid.UUID(other["id"]))).id)

    spoofed = await upload(pg_client, project["id"], data=TEXT, filename="x.png")
    too_big = await upload(pg_client, project["id"], data=png_of_size(MAX_IMAGE_BYTES + 1))
    wrong_project = await upload(pg_client, project["id"], transcript_id=foreign)
    unknown = await upload(pg_client, project["id"], transcript_id=str(uuid.uuid4()))

    assert [r.status_code for r in (spoofed, too_big, wrong_project, unknown)] == [
        415,
        413,
        422,
        422,
    ]
    assert await _count(pg_session) == 0


async def test_upload_exactly_5_mib_round_trips_through_bytea(
    pg_client: httpx2.AsyncClient,
) -> None:
    project = await create_project(pg_client)
    data = png_of_size(MAX_IMAGE_BYTES)

    shot = (await upload(pg_client, project["id"], data=data)).json()

    assert (await pg_client.get(shot["image_url"])).content == data


async def test_export_zip_tree_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project = await create_project(pg_client, "Lecture notes")
    project_id = uuid.UUID(project["id"])
    await add_transcript(pg_session, project_id, title="Notes", created_at=at(1))
    linked = await add_transcript(pg_session, project_id, title="Notes", created_at=at(2))
    linked_id = str(linked.id)
    uploads = [
        (JPEG, "Foto Pizarra.jpeg", None, 2),
        (PNG, "slide.png", None, 1),
        (WEBP, "!!!.webp", linked_id, 3),
    ]
    for data, name, transcript_id, minute in uploads:
        response = await upload(
            pg_client, project["id"], data=data, filename=name, transcript_id=transcript_id
        )
        assert response.status_code == 201, response.text
        await pg_session.execute(
            update(Screenshot)
            .where(Screenshot.id == uuid.UUID(response.json()["id"]))
            .values(created_at=at(minute))
        )
    await pg_session.commit()

    response = await pg_client.get(f"/api/projects/{project['id']}/export")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="lecture-notes.zip"'
    files = unzip(response.content)
    assert sorted(files) == [
        "lecture-notes/README.md",
        "lecture-notes/screenshots/01-slide.png",
        "lecture-notes/screenshots/02-foto-pizarra.jpg",
        "lecture-notes/screenshots/03-screenshot.webp",
        "lecture-notes/transcripts/notes-2.md",
        "lecture-notes/transcripts/notes-2.txt",
        "lecture-notes/transcripts/notes.md",
        "lecture-notes/transcripts/notes.txt",
    ]
    assert files["lecture-notes/screenshots/02-foto-pizarra.jpg"] == JPEG
    pg_session.expire_all()
    stored = await pg_session.get(Transcript, uuid.UUID(linked_id))
    assert stored is not None
    assert files["lecture-notes/transcripts/notes-2.md"] == render_markdown(stored).encode()
    assert files["lecture-notes/transcripts/notes-2.txt"] == render_text(stored).encode()
    assert "[notes-2.md](transcripts/notes-2.md)" in files["lecture-notes/README.md"].decode()


async def test_export_empty_project_on_postgres(pg_client: httpx2.AsyncClient) -> None:
    project = await create_project(pg_client, "Nada")

    files = unzip((await pg_client.get(f"/api/projects/{project['id']}/export")).content)

    assert list(files) == ["nada/README.md"]
    assert "This project is empty" in files["nada/README.md"].decode()


async def test_deleting_project_cascades_uploaded_screenshots_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project = await create_project(pg_client)
    shot = (await upload(pg_client, project["id"])).json()

    assert (await pg_client.delete(f"/api/projects/{project['id']}")).status_code == 204

    assert await _count(pg_session) == 0
    assert (await pg_client.get(shot["image_url"])).status_code == 404


async def test_deleting_transcript_unlinks_uploaded_screenshot_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project = await create_project(pg_client)
    transcript_id = (await add_transcript(pg_session, uuid.UUID(project["id"]))).id
    shot = (await upload(pg_client, project["id"], transcript_id=str(transcript_id))).json()
    assert shot["transcript_id"] == str(transcript_id)

    await pg_session.execute(delete(Transcript).where(Transcript.id == transcript_id))
    await pg_session.commit()

    listed = (await pg_client.get(f"/api/projects/{project['id']}/screenshots")).json()
    assert [(s["id"], s["transcript_id"]) for s in listed] == [(shot["id"], None)]
    assert await pg_session.get(Project, uuid.UUID(project["id"])) is not None
