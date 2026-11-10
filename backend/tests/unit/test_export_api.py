"""#15 / US-16 export endpoint on SQLite: headers, ZIP tree, file contents, privacy."""

import re
import uuid
from pathlib import PurePosixPath

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Screenshot, Transcript
from app.services import export as export_service
from app.services.transcript_format import render_markdown, render_text
from tests.image_utils import JPEG, PNG, WEBP, create_project, unzip, upload
from tests.log_utils import parse_json_logs
from tests.project_utils import add_transcript, at

pytestmark = pytest.mark.anyio

LINK = re.compile(r"\]\(([^)]+)\)")


async def _seed_shot(
    client: httpx2.AsyncClient,
    session: AsyncSession,
    project_id: str,
    minute: int,
    **kwargs: object,
) -> dict:
    response = await upload(client, project_id, **kwargs)  # type: ignore[arg-type]
    assert response.status_code == 201, response.text
    stored = await session.get(Screenshot, uuid.UUID(response.json()["id"]))
    assert stored is not None
    stored.created_at = at(minute)
    await session.commit()
    return response.json()


async def test_export_returns_zip_with_attachment_filename(client: httpx2.AsyncClient) -> None:
    project = await create_project(client, "Clase de Física")

    response = await client.get(f"/api/projects/{project['id']}/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"] == 'attachment; filename="clase-de-fisica.zip"'
    assert int(response.headers["content-length"]) == len(response.content)


async def test_export_unknown_project_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"/api/projects/{uuid.uuid4()}/export")

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found", "code": "not_found"}


async def test_export_empty_project_contains_only_readme_saying_empty(
    client: httpx2.AsyncClient,
) -> None:
    project = await create_project(client, "Empty")

    files = unzip((await client.get(f"/api/projects/{project['id']}/export")).content)

    assert list(files) == ["empty/README.md"]
    readme = files["empty/README.md"].decode()
    assert readme.startswith("# Empty\n")
    assert "This project is empty" in readme


async def test_export_zip_tree_matches_spec_and_readme_links_resolve(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await create_project(client, "Lecture notes")
    project_id = uuid.UUID(project["id"])
    older = await add_transcript(session, project_id, title="Notes", created_at=at(1))
    newer = await add_transcript(session, project_id, title="Notes", created_at=at(2))
    await _seed_shot(client, session, project["id"], 2, data=JPEG, filename="Photo 1.JPG")
    await _seed_shot(client, session, project["id"], 1, data=PNG, filename="slide.png")
    await _seed_shot(
        client,
        session,
        project["id"],
        3,
        data=WEBP,
        filename="!!!.webp",
        transcript_id=str(newer.id),
    )

    files = unzip((await client.get(f"/api/projects/{project['id']}/export")).content)

    root = "lecture-notes"
    assert set(files) == {
        f"{root}/README.md",
        f"{root}/transcripts/notes.md",
        f"{root}/transcripts/notes.txt",
        f"{root}/transcripts/notes-2.md",
        f"{root}/transcripts/notes-2.txt",
        f"{root}/screenshots/01-slide.png",
        f"{root}/screenshots/02-photo-1.jpg",
        f"{root}/screenshots/03-screenshot.webp",
    }
    assert files[f"{root}/screenshots/01-slide.png"] == PNG
    assert files[f"{root}/screenshots/02-photo-1.jpg"] == JPEG
    assert files[f"{root}/screenshots/03-screenshot.webp"] == WEBP
    readme = files[f"{root}/README.md"].decode()
    links = set(LINK.findall(readme))
    assert links == {
        str(PurePosixPath(name).relative_to(root)) for name in files if name != f"{root}/README.md"
    }
    for transcript, stem in ((older, "notes"), (newer, "notes-2")):
        stored = await session.get(Transcript, transcript.id)
        assert stored is not None
        assert files[f"{root}/transcripts/{stem}.md"] == render_markdown(stored).encode()
        assert files[f"{root}/transcripts/{stem}.txt"] == render_text(stored).encode()


async def test_export_logs_counts_and_size_but_no_names_or_text(
    client: httpx2.AsyncClient, session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    project = await create_project(client, "Confidential Project")
    await add_transcript(session, uuid.UUID(project["id"]), title="Secret Title")
    await _seed_shot(client, session, project["id"], 1, filename="Private-Shot.png")
    capsys.readouterr()

    response = await client.get(f"/api/projects/{project['id']}/export")

    output = capsys.readouterr().out
    for secret in ("Confidential", "Secret Title", "secret transcript text", "Private-Shot"):
        assert secret not in output
    exported = [r for r in parse_json_logs(output) if r.get("message") == "project exported"]
    assert len(exported) == 1
    assert (exported[0]["transcript_count"], exported[0]["screenshot_count"]) == (1, 1)
    assert exported[0]["size_bytes"] == len(response.content)


async def test_export_is_never_persisted_temp_file_is_closed_after_streaming(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = await create_project(client)
    spools: list[object] = []
    real_spool = export_service.SpooledTemporaryFile

    def recording_spool(*args: object, **kwargs: object) -> object:
        spool = real_spool(*args, **kwargs)  # type: ignore[call-overload]
        spools.append(spool)
        return spool

    monkeypatch.setattr(export_service, "SpooledTemporaryFile", recording_spool)

    response = await client.get(f"/api/projects/{project['id']}/export")

    assert response.status_code == 200
    assert len(spools) == 1
    assert spools[0].closed  # type: ignore[attr-defined]
