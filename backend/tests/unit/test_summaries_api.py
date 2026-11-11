"""US-22 API and job lifecycle on SQLite (AC1-AC5, AC12, AC15, AC18, AC19), fake/stub providers."""

import asyncio
import re
import uuid
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Summary
from app.summarization import (
    SummarizerError,
    SummarizerRateLimited,
    SummarizerTimeout,
    get_summarizer,
)
from app.summarization.render import TRUNCATION_NOTE
from tests.image_utils import unzip
from tests.summary_utils import (
    BlockingSummarizer,
    StubSummarizer,
    add_screenshot,
    add_transcript,
    create_project,
    generate,
    real_png,
    wait_for_summary_jobs,
)

pytestmark = pytest.mark.anyio


async def project_with_transcript(client: httpx2.AsyncClient, text: str = "hello") -> str:
    project = await create_project(client)
    await add_transcript(client, project["id"], text=text)
    return str(project["id"])


def use(app: FastAPI, summarizer: Any) -> None:
    app.dependency_overrides[get_summarizer] = lambda: summarizer


# --- AC1 / AC2 -----------------------------------------------------------------------------


async def test_post_returns_202_pending_and_the_job_succeeds_in_the_background(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project_id = await project_with_transcript(client)

    response = await client.post(f"/api/projects/{project_id}/summaries")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending" and body["project_id"] == project_id
    assert body["provider"] == "fake" and body["html"] is None and body["model"] is None
    assert body["started_at"] is None and body["finished_at"] is None
    await wait_for_summary_jobs(app)
    latest = (await client.get(f"/api/projects/{project_id}/summaries/latest")).json()
    assert latest["id"] == body["id"] and latest["status"] == "succeeded"
    assert latest["model"] == "fake-summarizer" and latest["error_code"] is None
    assert latest["started_at"] and latest["finished_at"]
    assert latest["transcript_count"] == 1 and latest["truncated"] is False
    assert latest["html"].startswith("<!doctype html>")


async def test_post_without_transcripts_returns_409_no_transcripts(
    client: httpx2.AsyncClient,
) -> None:
    project = await create_project(client)

    response = await client.post(f"/api/projects/{project['id']}/summaries")

    assert response.status_code == 409
    assert response.json()["code"] == "no_transcripts"


async def test_post_for_an_unknown_project_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.post(f"/api/projects/{uuid.uuid4()}/summaries")

    assert response.status_code == 404 and response.json()["code"] == "not_found"


async def test_latest_returns_404_summary_not_found_when_there_was_never_one(
    client: httpx2.AsyncClient,
) -> None:
    project_id = await project_with_transcript(client)

    response = await client.get(f"/api/projects/{project_id}/summaries/latest")

    assert response.status_code == 404 and response.json()["code"] == "summary_not_found"


async def test_latest_for_an_unknown_project_returns_404(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"/api/projects/{uuid.uuid4()}/summaries/latest")

    assert response.status_code == 404


# --- AC4: one active job per project --------------------------------------------------------


async def test_post_while_a_job_is_active_returns_the_same_summary_and_starts_no_job(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    blocking = BlockingSummarizer()
    use(app, blocking)
    project_id = await project_with_transcript(client)
    first = (await client.post(f"/api/projects/{project_id}/summaries")).json()
    await asyncio.wait_for(blocking.started.wait(), 5)

    second = await client.post(f"/api/projects/{project_id}/summaries")
    running = (await client.get(f"/api/projects/{project_id}/summaries/latest")).json()

    assert second.status_code == 202 and second.json()["id"] == first["id"]
    assert second.json()["status"] == "running" and running["status"] == "running"
    assert running["html"] is None
    blocking.release.set()
    await wait_for_summary_jobs(app)
    assert blocking.calls == 1


async def test_partial_unique_index_rejects_a_second_active_summary(
    session: AsyncSession, client: httpx2.AsyncClient
) -> None:
    project_id = uuid.UUID(await project_with_transcript(client))
    session.add(Summary(project_id=project_id, status="pending", provider="fake"))
    session.add(Summary(project_id=project_id, status="failed", provider="fake"))
    await session.commit()
    session.add(Summary(project_id=project_id, status="running", provider="fake"))

    with pytest.raises(IntegrityError):
        await session.commit()


# --- AC3: download ---------------------------------------------------------------------------


async def test_download_returns_the_self_contained_html_attachment(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project_id = await project_with_transcript(client)
    summary = await generate(app, client, project_id)

    response = await client.get(f"/api/projects/{project_id}/summaries/{summary['id']}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="summary.html"'
    assert response.text == summary["html"]
    assert not re.search(r"(src|href)\s*=\s*\"https?:", response.text)


async def test_download_of_an_unfinished_summary_returns_409_summary_not_ready(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    blocking = BlockingSummarizer()
    use(app, blocking)
    project_id = await project_with_transcript(client)
    summary = (await client.post(f"/api/projects/{project_id}/summaries")).json()

    response = await client.get(f"/api/projects/{project_id}/summaries/{summary['id']}/download")

    assert response.status_code == 409 and response.json()["code"] == "summary_not_ready"
    blocking.release.set()
    await wait_for_summary_jobs(app)


async def test_download_of_a_failed_summary_returns_409(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    use(app, StubSummarizer(error=SummarizerError("fake", 500)))
    project_id = await project_with_transcript(client)
    summary = await generate(app, client, project_id)

    response = await client.get(f"/api/projects/{project_id}/summaries/{summary['id']}/download")

    assert response.status_code == 409


async def test_download_with_an_unknown_or_other_project_id_returns_404(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project_id = await project_with_transcript(client)
    other_id = await project_with_transcript(client)
    summary = await generate(app, client, project_id)

    other = await client.get(f"/api/projects/{other_id}/summaries/{summary['id']}/download")
    unknown = await client.get(f"/api/projects/{project_id}/summaries/{uuid.uuid4()}/download")

    assert other.status_code == 404 and other.json()["code"] == "summary_not_found"
    assert unknown.status_code == 404 and unknown.json()["code"] == "summary_not_found"


# --- AC5: regeneration ------------------------------------------------------------------------


async def _summary_ids(factory: async_sessionmaker[AsyncSession]) -> list[uuid.UUID]:
    async with factory() as session:
        return list((await session.scalars(select(Summary.id))).all())


async def test_a_new_successful_summary_replaces_the_previous_one(
    app: FastAPI, client: httpx2.AsyncClient, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    project_id = await project_with_transcript(client)
    old = await generate(app, client, project_id)

    new = await generate(app, client, project_id)

    assert new["id"] != old["id"] and new["status"] == "succeeded"
    assert await _summary_ids(session_maker) == [uuid.UUID(new["id"])]
    gone = await client.get(f"/api/projects/{project_id}/summaries/{old['id']}/download")
    assert gone.status_code == 404


async def test_a_failed_regeneration_keeps_the_previous_summary_downloadable_and_exported(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project_id = await project_with_transcript(client)
    old = await generate(app, client, project_id)
    use(app, StubSummarizer(error=SummarizerTimeout("fake")))

    failed = await generate(app, client, project_id)

    assert failed["status"] == "failed" and failed["id"] != old["id"]
    download = await client.get(f"/api/projects/{project_id}/summaries/{old['id']}/download")
    assert download.status_code == 200
    files = unzip((await client.get(f"/api/projects/{project_id}/export")).content)
    summary_paths = [name for name in files if name.endswith("/summary.html")]
    assert len(summary_paths) == 1 and files[summary_paths[0]] == download.content


# --- AC19: failures -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (SummarizerError("fake", 500), "provider_error"),
        (SummarizerRateLimited("fake"), "provider_error"),
        (SummarizerTimeout("fake"), "provider_timeout"),
        (RuntimeError("bug"), "internal_error"),
    ],
)
async def test_provider_failures_end_failed_with_a_safe_error_code(
    app: FastAPI, client: httpx2.AsyncClient, error: Exception, code: str
) -> None:
    use(app, StubSummarizer(error=error))
    project_id = await project_with_transcript(client)

    summary = await generate(app, client, project_id)

    assert summary["status"] == "failed" and summary["error_code"] == code
    assert summary["html"] is None and summary["finished_at"]


async def test_a_provider_slower_than_the_timeout_ends_provider_timeout(
    app: FastAPI, client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMMARY_TIMEOUT_SECONDS", "0.05")
    get_settings.cache_clear()
    use(app, BlockingSummarizer())  # never released
    project_id = await project_with_transcript(client)

    summary = await generate(app, client, project_id)

    assert summary["status"] == "failed" and summary["error_code"] == "provider_timeout"


# --- AC12: ZIP export ---------------------------------------------------------------------


async def test_zip_contains_summary_html_and_readme_links_it(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project_id = await project_with_transcript(client)
    summary = await generate(app, client, project_id)
    download = await client.get(f"/api/projects/{project_id}/summaries/{summary['id']}/download")

    files = unzip((await client.get(f"/api/projects/{project_id}/export")).content)

    assert files["notes/summary.html"] == download.content
    assert "[summary.html](summary.html)" in files["notes/README.md"].decode()


async def test_zip_is_unchanged_without_a_succeeded_summary(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    use(app, StubSummarizer(error=SummarizerError("fake")))
    project_id = await project_with_transcript(client)
    await generate(app, client, project_id)

    files = unzip((await client.get(f"/api/projects/{project_id}/export")).content)

    assert not any(name.endswith("summary.html") for name in files)
    assert "summary" not in files["notes/README.md"].decode().lower()


# --- AC13 / AC15: content, images, caps -------------------------------------------------------


async def test_screenshots_are_sent_downscaled_and_embedded_as_data_uris(
    app: FastAPI, client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMMARY_IMAGE_MAX_PX", "32")
    get_settings.cache_clear()
    stub = StubSummarizer(
        fragment='<h1>T</h1><figure data-screenshot="1"><figcaption>Board</figcaption></figure>'
    )
    use(app, stub)
    project = await create_project(client)
    transcript = await add_transcript(client, project["id"])
    await add_screenshot(client, project["id"], real_png(200, 100), transcript_id=transcript["id"])

    summary = await generate(app, client, project["id"])

    assert summary["image_count"] == 1 and summary["truncated"] is False
    assert stub.requests[0].images[0].mime_type == "image/png"
    assert '<img src="data:image/png;base64,' in summary["html"]
    assert "<figcaption>Board</figcaption>" in summary["html"]


async def test_over_the_caps_the_summary_is_marked_truncated(
    app: FastAPI, client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMMARY_MAX_CHARS", "10")
    monkeypatch.setenv("SUMMARY_MAX_IMAGES", "1")
    get_settings.cache_clear()
    stub = StubSummarizer()
    use(app, stub)
    project = await create_project(client)
    await add_transcript(client, project["id"], text="x" * 50)
    for _ in range(2):
        await add_screenshot(client, project["id"], real_png())

    summary = await generate(app, client, project["id"])

    assert summary["truncated"] is True and summary["image_count"] == 1
    assert TRUNCATION_NOTE in summary["html"]
    assert "truncated content" in stub.requests[0].system_instruction


async def test_undecodable_screenshots_are_skipped(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project_id = await project_with_transcript(client)
    await add_screenshot(client, project_id, b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)

    summary = await generate(app, client, project_id)

    assert summary["status"] == "succeeded" and summary["image_count"] == 0


# --- AC18 + lifecycle -------------------------------------------------------------------------


async def test_startup_marks_pending_and_running_summaries_interrupted(
    app: FastAPI, client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project_id = uuid.UUID(await project_with_transcript(client))
    other_id = uuid.UUID(await project_with_transcript(client))
    session.add(Summary(project_id=project_id, status="running", provider="fake"))
    session.add(Summary(project_id=other_id, status="pending", provider="fake"))
    await session.commit()

    async with app.router.lifespan_context(app):
        latest = (await client.get(f"/api/projects/{project_id}/summaries/latest")).json()
        other = (await client.get(f"/api/projects/{other_id}/summaries/latest")).json()

    assert latest["status"] == "failed" and latest["error_code"] == "interrupted"
    assert other["status"] == "failed" and other["error_code"] == "interrupted"
    assert latest["finished_at"]


async def test_shutdown_cancels_running_jobs(app: FastAPI, client: httpx2.AsyncClient) -> None:
    blocking = BlockingSummarizer()
    use(app, blocking)
    project_id = await project_with_transcript(client)

    async with app.router.lifespan_context(app):
        await client.post(f"/api/projects/{project_id}/summaries")
        await asyncio.wait_for(blocking.started.wait(), 5)
        assert len(app.state.summary_tasks) == 1

    assert app.state.summary_tasks == set()


async def test_deleting_the_project_deletes_its_summaries(
    app: FastAPI, client: httpx2.AsyncClient, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    project_id = await project_with_transcript(client)
    await generate(app, client, project_id)

    assert (await client.delete(f"/api/projects/{project_id}")).status_code == 204

    assert await _summary_ids(session_maker) == []
