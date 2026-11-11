"""US-22 API and job lifecycle on SQLite (AC1-AC5, AC12, AC15, AC18, AC19), fake/stub providers."""

import asyncio
import base64
import io
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.base import utcnow
from app.db.models import Summary
from app.services import summaries as service
from app.summarization import (
    SummarizerError,
    SummarizerRateLimited,
    SummarizerTimeout,
    get_summarizer,
)
from app.summarization.gemini import GeminiSummarizer
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


# --- AC18: stale active jobs (orphaned by an overlapping deploy) ------------------------------


def _stale_age() -> timedelta:
    return service.stale_after(get_settings())


async def _add_active(
    session: AsyncSession, project_id: str, age: timedelta, status: str = "running"
) -> uuid.UUID:
    row = Summary(
        project_id=uuid.UUID(project_id),
        status=status,
        provider="fake",
        created_at=utcnow() - age,
    )
    session.add(row)
    await session.commit()
    return row.id


async def _row(
    session_maker: async_sessionmaker[AsyncSession], summary_id: uuid.UUID
) -> Summary | None:
    async with session_maker() as fresh:
        return await fresh.get(Summary, summary_id)


def test_stale_threshold_is_the_summary_timeout_plus_60_seconds() -> None:
    assert _stale_age() == timedelta(seconds=get_settings().summary_timeout_seconds + 60)


@pytest.mark.parametrize("status", ["pending", "running"])
async def test_post_marks_a_stale_active_summary_interrupted_and_starts_a_new_job(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    session_maker: async_sessionmaker[AsyncSession],
    status: str,
) -> None:
    blocking = BlockingSummarizer()
    use(app, blocking)
    project_id = await project_with_transcript(client)
    stale_id = await _add_active(session, project_id, _stale_age() + timedelta(seconds=1), status)

    response = await client.post(f"/api/projects/{project_id}/summaries")

    assert response.status_code == 202
    body = response.json()
    assert body["id"] != str(stale_id) and body["status"] == "pending"
    stale = await _row(session_maker, stale_id)
    assert stale is not None and stale.status == "failed"
    assert stale.error_code == "interrupted" and stale.finished_at is not None
    await asyncio.wait_for(blocking.started.wait(), 5)
    assert blocking.calls == 1
    blocking.release.set()
    await wait_for_summary_jobs(app)
    latest = (await client.get(f"/api/projects/{project_id}/summaries/latest")).json()
    assert latest["id"] == body["id"] and latest["status"] == "succeeded"


async def test_latest_reports_a_stale_active_summary_as_failed_interrupted(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await project_with_transcript(client)
    stale_id = await _add_active(session, project_id, _stale_age() + timedelta(seconds=1))

    latest = (await client.get(f"/api/projects/{project_id}/summaries/latest")).json()

    assert latest["id"] == str(stale_id)
    assert latest["status"] == "failed" and latest["error_code"] == "interrupted"
    assert latest["finished_at"]
    stale = await _row(session_maker, stale_id)  # persisted: consistent with the next POST
    assert stale is not None and stale.status == "failed" and stale.error_code == "interrupted"
    started = (await client.post(f"/api/projects/{project_id}/summaries")).json()
    assert started["id"] != str(stale_id) and started["status"] == "pending"
    await wait_for_summary_jobs(app)


async def test_an_active_summary_younger_than_the_threshold_is_still_returned_by_post(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    project_id = await project_with_transcript(client)
    active_id = await _add_active(session, project_id, _stale_age() - timedelta(seconds=5))

    response = await client.post(f"/api/projects/{project_id}/summaries")
    latest = (await client.get(f"/api/projects/{project_id}/summaries/latest")).json()

    assert response.status_code == 202
    assert response.json()["id"] == str(active_id) and response.json()["status"] == "running"
    assert latest["id"] == str(active_id) and latest["status"] == "running"
    assert app.state.summary_tasks == set()  # AC4: no second job
    row = await _row(session_maker, active_id)
    assert row is not None and row.status == "running" and row.error_code is None


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


@pytest.mark.parametrize("status", [503, 500, 429])
async def test_gemini_overloaded_on_both_models_ends_provider_error(
    app: FastAPI, client: httpx2.AsyncClient, status: int
) -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path.rsplit("/", 1)[-1])
        return httpx2.Response(status, json={"error": {"status": "UNAVAILABLE"}})

    use(app, _mock_gemini(handler))
    project_id = await project_with_transcript(client)

    summary = await generate(app, client, project_id)

    assert seen == ["flash:generateContent", "flash-lite:generateContent"]
    assert summary["status"] == "failed" and summary["error_code"] == "provider_error"


def _mock_gemini(handler: Any) -> GeminiSummarizer:
    return GeminiSummarizer(
        api_key=SecretStr("test-key"),
        base_url="https://gemini.invalid/v1beta",
        model="flash",
        fallback_model="flash-lite",
        timeout_seconds=5,
        primary_timeout_seconds=0.1,
        transport=httpx2.MockTransport(handler),
    )


async def test_gemini_primary_timeout_falls_back_and_the_summary_records_the_fallback_model(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        if "/models/flash:" in str(request.url):
            await asyncio.sleep(30)  # the primary model hangs past GEMINI_PRIMARY_TIMEOUT_SECONDS
        return httpx2.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "<h1>Lite</h1>"}]}}]}
        )

    use(app, _mock_gemini(handler))
    project_id = await project_with_transcript(client)

    summary = await generate(app, client, project_id)

    assert summary["status"] == "succeeded" and summary["model"] == "flash-lite"
    assert summary["provider"] == "gemini" and "<h1>Lite</h1>" in summary["html"]


async def test_gemini_timeout_on_both_models_ends_provider_timeout(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    use(app, _mock_gemini(handler))
    project_id = await project_with_transcript(client)

    summary = await generate(app, client, project_id)

    assert summary["status"] == "failed" and summary["error_code"] == "provider_timeout"


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


async def test_the_image_count_cap_alone_marks_the_summary_truncated(
    app: FastAPI, client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMMARY_MAX_IMAGES", "1")
    get_settings.cache_clear()
    stub = StubSummarizer()
    use(app, stub)
    project_id = await project_with_transcript(client, text="short")  # far under the char cap
    for _ in range(2):
        await add_screenshot(client, project_id, real_png())

    summary = await generate(app, client, project_id)

    assert "short" in stub.requests[0].user_text  # the text was sent whole
    assert summary["truncated"] is True and summary["image_count"] == 1
    assert len(stub.requests[0].images) == 1 and TRUNCATION_NOTE in summary["html"]


async def test_a_smaller_later_image_is_included_after_one_exceeds_the_byte_budget(
    app: FastAPI, client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = 20_000
    monkeypatch.setenv("SUMMARY_MAX_IMAGE_BYTES", str(budget))
    get_settings.cache_clear()
    stub = StubSummarizer()
    use(app, stub)
    project = await create_project(client)
    transcript = await add_transcript(client, project["id"])
    # Linked screenshots are tried oldest first: the big one first, then the small one.
    big = _noise_png(400, 300)  # tens of KB as JPEG: over the budget on its own
    await add_screenshot(client, project["id"], big, transcript_id=transcript["id"])
    small = real_png(64, 48)  # a few hundred bytes
    await add_screenshot(client, project["id"], small, transcript_id=transcript["id"])

    summary = await generate(app, client, project["id"])

    sent = stub.requests[0].images
    assert len(sent) == 1 and len(sent[0].data) < 1_000 and sent[0].mime_type == "image/png"
    assert summary["image_count"] == 1 and summary["truncated"] is True


async def test_undecodable_screenshots_are_skipped(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project_id = await project_with_transcript(client)
    await add_screenshot(client, project_id, b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)

    summary = await generate(app, client, project_id)

    assert summary["status"] == "succeeded" and summary["image_count"] == 0
    assert summary["truncated"] is False  # skipping an unreadable image is not truncation


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
async def test_an_image_over_the_pixel_cap_is_skipped_and_the_job_succeeds(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project_id = await project_with_transcript(client)
    output = io.BytesIO()
    Image.new("1", (6300, 6300)).save(output, format="PNG")  # small file, 39.7 MP canvas
    await add_screenshot(client, project_id, output.getvalue())
    await add_screenshot(client, project_id, real_png())

    summary = await generate(app, client, project_id)

    assert summary["status"] == "succeeded"
    assert summary["image_count"] == 1 and summary["truncated"] is False


@pytest.mark.parametrize("number", ["²", "①"])
async def test_a_unicode_digit_screenshot_number_is_dropped_and_the_job_succeeds(
    app: FastAPI, client: httpx2.AsyncClient, number: str
) -> None:
    fragment = f'<h1>T</h1><figure data-screenshot="{number}"><figcaption>x</figcaption></figure>'
    use(app, StubSummarizer(fragment=fragment))
    project_id = await project_with_transcript(client)
    await add_screenshot(client, project_id, real_png())

    summary = await generate(app, client, project_id)

    assert summary["status"] == "succeeded" and "<img" not in summary["html"]


def _noise_png(width: int, height: int) -> bytes:
    output = io.BytesIO()
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(
        output, format="PNG"
    )
    return output.getvalue()


async def test_embedded_images_stay_within_the_byte_budget_and_mark_truncated(
    app: FastAPI, client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = 150_000
    monkeypatch.setenv("SUMMARY_MAX_IMAGE_BYTES", str(budget))
    get_settings.cache_clear()
    stub = StubSummarizer(
        fragment="".join(
            f'<figure data-screenshot="{n}"><figcaption>s{n}</figcaption></figure>'
            for n in range(1, 9)
        )
    )
    use(app, stub)
    project_id = await project_with_transcript(client)
    for _ in range(4):  # each about 60-90 KB as JPEG: only one or two fit
        await add_screenshot(client, project_id, _noise_png(400, 300))

    summary = await generate(app, client, project_id)

    sent = stub.requests[0].images
    assert 1 <= len(sent) < 4 and summary["image_count"] == len(sent)
    assert sum(len(image.data) for image in sent) <= budget
    assert summary["truncated"] is True and TRUNCATION_NOTE in summary["html"]
    for image in sent:  # the same bytes went to the provider and into the HTML
        assert base64.b64encode(image.data).decode() in summary["html"]


async def test_eight_default_screenshots_stay_under_the_default_budget(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    stub = StubSummarizer()
    use(app, stub)
    project_id = await project_with_transcript(client)
    for _ in range(8):
        await add_screenshot(client, project_id, _noise_png(1600, 1000))

    summary = await generate(app, client, project_id)

    sent = stub.requests[0].images
    assert sum(len(image.data) for image in sent) <= get_settings().summary_max_image_bytes
    assert all(image.mime_type == "image/jpeg" for image in sent)
    assert summary["image_count"] == len(sent)


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


async def test_shutdown_cancels_running_jobs_and_marks_them_interrupted(
    app: FastAPI, client: httpx2.AsyncClient, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    blocking = BlockingSummarizer()
    use(app, blocking)
    project_id = await project_with_transcript(client)

    async with app.router.lifespan_context(app):
        started = (await client.post(f"/api/projects/{project_id}/summaries")).json()
        await asyncio.wait_for(blocking.started.wait(), 5)
        assert len(app.state.summary_tasks) == 1

    assert app.state.summary_tasks == set()
    row = await _row(session_maker, uuid.UUID(started["id"]))
    assert row is not None and row.status == "failed" and row.error_code == "interrupted"
    assert row.finished_at is not None


async def test_shutdown_swallows_a_failing_interrupted_write(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocking = BlockingSummarizer()
    use(app, blocking)
    project_id = await project_with_transcript(client)

    def broken(*_criteria: Any) -> Any:
        raise RuntimeError("database is gone")

    with caplog.at_level(logging.WARNING, logger="app.services.summaries"):
        async with app.router.lifespan_context(app):
            started = (await client.post(f"/api/projects/{project_id}/summaries")).json()
            await asyncio.wait_for(blocking.started.wait(), 5)
            monkeypatch.setattr(service, "_interrupt", broken)

    assert app.state.summary_tasks == set()  # shutdown completed without raising
    row = await _row(session_maker, uuid.UUID(started["id"]))
    assert row is not None and row.status == "running"  # startup recovery fixes it later
    warnings = [r for r in caplog.records if r.getMessage() == "summary interruption not stored"]
    assert len(warnings) == 1 and getattr(warnings[0], "error_type", None) == "RuntimeError"


async def test_the_shutdown_interrupted_write_gives_up_after_a_short_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "SHUTDOWN_WRITE_TIMEOUT_SECONDS", 0.05)

    @asynccontextmanager
    async def hanging_factory() -> Any:
        await asyncio.Event().wait()  # the database never answers
        yield None

    began = time.monotonic()
    await service._store_interrupted_on_cancel(hanging_factory, uuid.uuid4(), {})  # type: ignore[arg-type]

    assert time.monotonic() - began < 2


async def test_deleting_the_project_deletes_its_summaries(
    app: FastAPI, client: httpx2.AsyncClient, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    project_id = await project_with_transcript(client)
    await generate(app, client, project_id)

    assert (await client.delete(f"/api/projects/{project_id}")).status_code == 204

    assert await _summary_ids(session_maker) == []
