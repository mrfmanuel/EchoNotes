"""#23: the whole journey through the ASGI app on a real Postgres, plus the privacy check.

create project → upload audio (fake provider) → edit transcript → attach a linked screenshot
→ export ZIP (exact tree + README links) → delete project (cascade, no rows left).
The app runs at LOG_LEVEL=DEBUG here so the privacy test sees every log line it could emit.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Project, Screenshot, Transcript
from app.db.session import get_session
from app.main import create_app
from tests.image_utils import PNG, unzip
from tests.image_utils import upload as upload_screenshot
from tests.transcription_utils import AUDIO
from tests.transcription_utils import upload as upload_audio

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

# Distinctive user content: none of it may ever appear in a log line.
PROJECT_NAME = "Zanzibar Quokka Seminar"
AUDIO_FILENAME = "quokka-lecture-7f3a.m4a"
TRANSCRIPT_TITLE = "Marsupial Secrets 9b2e"
EDITED_TEXT = "EDITED-TEXT-MARKER-4c1d: quokkas smile at tourists."
SCREENSHOT_FILENAME = "Whiteboard Quokka 5e6f.png"
FAKE_TEXT = f"[fake transcript] {AUDIO_FILENAME} ({len(AUDIO)} bytes)"
USER_CONTENT = (
    PROJECT_NAME,
    AUDIO_FILENAME,
    TRANSCRIPT_TITLE,
    EDITED_TEXT,
    FAKE_TEXT,
    SCREENSHOT_FILENAME,
    "quokka",  # any fragment of the content above, case-insensitive check below
)


@pytest.fixture
def pg_app(
    monkeypatch: pytest.MonkeyPatch, pg_session_maker: async_sessionmaker[AsyncSession]
) -> FastAPI:
    """The Postgres-backed app, configured at LOG_LEVEL=DEBUG (overrides the conftest one)."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    get_settings.cache_clear()
    app = create_app()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_maker() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return app


@dataclass(frozen=True)
class FlowResult:
    project: dict[str, Any]
    transcript: dict[str, Any]
    screenshot: dict[str, Any]
    files: dict[str, bytes]


async def _count(session: AsyncSession, model: type[Project | Transcript | Screenshot]) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def run_full_flow(client: httpx2.AsyncClient) -> FlowResult:
    created = await client.post("/api/projects", json={"name": PROJECT_NAME})
    assert created.status_code == 201, created.text
    project = created.json()

    uploaded = await upload_audio(
        client, project["id"], AUDIO_FILENAME, title=TRANSCRIPT_TITLE, language="es"
    )
    assert uploaded.status_code == 201, uploaded.text
    assert (uploaded.json()["text"], uploaded.json()["provider"]) == (FAKE_TEXT, "fake")

    edited = await client.patch(
        f"/api/transcriptions/{uploaded.json()['id']}", json={"text": EDITED_TEXT}
    )
    assert edited.status_code == 200, edited.text
    transcript = edited.json()
    assert (transcript["text"], transcript["title"]) == (EDITED_TEXT, TRANSCRIPT_TITLE)

    attached = await upload_screenshot(
        client, project["id"], PNG, SCREENSHOT_FILENAME, transcript_id=transcript["id"]
    )
    assert attached.status_code == 201, attached.text
    screenshot = attached.json()
    assert screenshot["transcript_id"] == transcript["id"]

    exported = await client.get(f"/api/projects/{project['id']}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    return FlowResult(project, transcript, screenshot, unzip(exported.content))


async def test_full_flow_create_upload_edit_attach_export_delete_on_postgres(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    flow = await run_full_flow(pg_client)
    root, slug = flow.project["slug"], flow.transcript["slug"]
    assert (root, slug) == ("zanzibar-quokka-seminar", "marsupial-secrets-9b2e")

    # Export: the exact file tree, the edited text and the README index links.
    md, txt = f"transcripts/{slug}.md", f"transcripts/{slug}.txt"
    image = "screenshots/01-whiteboard-quokka-5e6f.png"
    assert sorted(flow.files) == sorted(f"{root}/{path}" for path in ("README.md", md, txt, image))
    assert EDITED_TEXT in flow.files[f"{root}/{md}"].decode()
    assert EDITED_TEXT in flow.files[f"{root}/{txt}"].decode()
    assert FAKE_TEXT not in flow.files[f"{root}/{md}"].decode()
    assert flow.files[f"{root}/{image}"] == PNG
    readme = flow.files[f"{root}/README.md"].decode()
    assert readme.startswith(f"# {PROJECT_NAME}\n")
    assert f"[{slug}.md]({md}) · [{slug}.txt]({txt})" in readme
    assert f"| 1 | [01-whiteboard-quokka-5e6f.png]({image}) | [{slug}.md]({md}) |" in readme

    # Delete: the database cascades transcripts and screenshots.
    deleted = await pg_client.delete(f"/api/projects/{flow.project['id']}")
    assert deleted.status_code == 204
    for model in (Project, Transcript, Screenshot):
        assert await _count(pg_session, model) == 0, model.__name__
    assert (await pg_client.get(f"/api/transcriptions/{flow.transcript['id']}")).status_code == 404
    assert (await pg_client.get(flow.screenshot["image_url"])).status_code == 404


async def test_full_flow_logs_no_user_content_at_debug_level(
    pg_client: httpx2.AsyncClient,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    capsys.readouterr()

    flow = await run_full_flow(pg_client)
    await pg_client.get(f"/api/transcriptions/{flow.transcript['id']}/download?format=md")
    assert (await pg_client.delete(f"/api/projects/{flow.project['id']}")).status_code == 204

    captured = capsys.readouterr()
    stdout_lines = [line for line in captured.out.splitlines() if line.strip()]
    assert any('"logger": "app.access"' in line for line in stdout_lines)  # logs were captured
    assert caplog.records
    texts = [*stdout_lines, *captured.err.splitlines()]
    for record in caplog.records:
        texts.append(record.getMessage())
        texts.extend(repr(value) for value in vars(record).values())
    for text in texts:
        lowered = text.lower()
        for secret in USER_CONTENT:
            assert secret.lower() not in lowered, f"user content leaked into a log line: {text}"
