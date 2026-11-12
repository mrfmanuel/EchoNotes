"""#58 / US-22 on a real Postgres with the `fake` provider (never Gemini or Groq)."""

import asyncio
import uuid
from datetime import timedelta

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from app.config import get_settings
from app.db.base import utcnow
from app.db.models import Summary
from app.main import create_app
from app.services.summaries import stale_after
from app.summarization import get_summarizer
from tests.image_utils import unzip
from tests.integration.conftest import alembic_config
from tests.summary_utils import (
    BlockingSummarizer,
    add_screenshot,
    add_transcript,
    create_project,
    real_png,
    wait_for_summary_jobs,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

POLL_SECONDS = 0.05
POLL_LIMIT = 200


async def poll_until_finished(client: httpx2.AsyncClient, project_id: str) -> dict:
    """What the UI does: GET latest until the status is terminal."""
    for _ in range(POLL_LIMIT):
        latest = (await client.get(f"/api/projects/{project_id}/summaries/latest")).json()
        if latest["status"] in ("succeeded", "failed"):
            return latest
        await asyncio.sleep(POLL_SECONDS)
    raise AssertionError("summary did not finish")


async def test_full_flow_transcript_screenshot_summary_download_and_zip(
    pg_client: httpx2.AsyncClient,
) -> None:
    project = await create_project(pg_client, "Física notes")
    transcript = await add_transcript(pg_client, project["id"], "Lecture", "Hola, la clase de hoy.")
    await add_screenshot(
        pg_client, project["id"], real_png(300, 200), transcript_id=transcript["id"]
    )

    started = await pg_client.post(f"/api/projects/{project['id']}/summaries")
    assert started.status_code == 202 and started.json()["status"] == "pending"
    summary = await poll_until_finished(pg_client, project["id"])

    assert summary["id"] == started.json()["id"] and summary["status"] == "succeeded"
    assert summary["transcript_count"] == 1 and summary["image_count"] == 1
    assert summary["provider"] == "fake" and summary["model"] == "fake-summarizer"
    assert '<img src="data:image/png;base64,' in summary["html"]
    download = await pg_client.get(
        f"/api/projects/{project['id']}/summaries/{summary['id']}/download"
    )
    assert download.status_code == 200 and download.text == summary["html"]
    assert download.headers["content-disposition"] == 'attachment; filename="summary.html"'
    files = unzip((await pg_client.get(f"/api/projects/{project['id']}/export")).content)
    assert files["fisica-notes/summary.html"] == download.content
    assert "[summary.html](summary.html)" in files["fisica-notes/README.md"].decode()


async def test_concurrent_posts_share_one_running_job(
    pg_app: FastAPI, pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    blocking = BlockingSummarizer()
    pg_app.dependency_overrides[get_summarizer] = lambda: blocking
    project = await create_project(pg_client)
    await add_transcript(pg_client, project["id"])

    responses = await asyncio.gather(
        *(pg_client.post(f"/api/projects/{project['id']}/summaries") for _ in range(5))
    )

    assert {r.status_code for r in responses} == {202}
    assert len({r.json()["id"] for r in responses}) == 1
    await asyncio.wait_for(blocking.started.wait(), 5)
    active = await pg_session.scalar(
        select(func.count(Summary.id)).where(Summary.status.in_(("pending", "running")))
    )
    assert active == 1
    blocking.release.set()
    await wait_for_summary_jobs(pg_app)
    assert blocking.calls == 1


async def test_partial_unique_index_allows_one_active_summary_per_project(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project_id = uuid.UUID((await create_project(pg_client))["id"])
    pg_session.add_all(
        [
            Summary(project_id=project_id, status="succeeded", provider="fake"),
            Summary(project_id=project_id, status="failed", provider="fake"),
            Summary(project_id=project_id, status="running", provider="fake"),
        ]
    )
    await pg_session.commit()
    pg_session.add(Summary(project_id=project_id, status="pending", provider="fake"))

    with pytest.raises(IntegrityError):
        await pg_session.commit()


async def test_restart_marks_running_summaries_failed_interrupted(
    pg_client: httpx2.AsyncClient, pg_session: AsyncSession, use_test_database: str
) -> None:
    project = await create_project(pg_client)
    await add_transcript(pg_client, project["id"])
    stale = Summary(project_id=uuid.UUID(project["id"]), status="running", provider="gemini")
    pg_session.add(stale)
    await pg_session.commit()

    restarted = create_app()  # a new process: real session factory from DATABASE_URL
    async with restarted.router.lifespan_context(restarted):
        pass

    latest = (await pg_client.get(f"/api/projects/{project['id']}/summaries/latest")).json()
    assert latest["id"] == str(stale.id)
    assert latest["status"] == "failed" and latest["error_code"] == "interrupted"
    assert latest["finished_at"] is not None


async def test_stale_running_summary_is_interrupted_and_replaced_under_the_unique_index(
    pg_app: FastAPI, pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project = await create_project(pg_client)
    await add_transcript(pg_client, project["id"])
    stale = Summary(
        project_id=uuid.UUID(project["id"]),
        status="running",
        provider="gemini",
        created_at=utcnow() - stale_after(get_settings()) - timedelta(seconds=1),
    )
    pg_session.add(stale)
    await pg_session.commit()

    reported = (await pg_client.get(f"/api/projects/{project['id']}/summaries/latest")).json()
    responses = await asyncio.gather(
        *(pg_client.post(f"/api/projects/{project['id']}/summaries") for _ in range(3))
    )

    assert reported["status"] == "failed" and reported["error_code"] == "interrupted"
    assert {r.status_code for r in responses} == {202}
    new_ids = {r.json()["id"] for r in responses}
    assert len(new_ids) == 1 and str(stale.id) not in new_ids
    await wait_for_summary_jobs(pg_app)
    summary = await poll_until_finished(pg_client, project["id"])
    assert summary["id"] in new_ids and summary["status"] == "succeeded"


async def test_post_alone_interrupts_a_stale_pending_summary_and_starts_a_new_job(
    pg_app: FastAPI, pg_client: httpx2.AsyncClient, pg_session: AsyncSession
) -> None:
    project = await create_project(pg_client)
    await add_transcript(pg_client, project["id"])
    stale = Summary(
        project_id=uuid.UUID(project["id"]),
        status="pending",
        provider="gemini",
        created_at=utcnow() - stale_after(get_settings()) - timedelta(seconds=1),
    )
    pg_session.add(stale)
    await pg_session.commit()

    started = await pg_client.post(f"/api/projects/{project['id']}/summaries")

    assert started.status_code == 202 and started.json()["status"] == "pending"
    assert started.json()["id"] != str(stale.id)
    await wait_for_summary_jobs(pg_app)
    summary = await poll_until_finished(pg_client, project["id"])
    assert summary["id"] == started.json()["id"] and summary["status"] == "succeeded"


def test_summaries_migration_downgrades_and_upgrades(
    migrated_database: str, use_test_database: str
) -> None:
    config = alembic_config()

    command.downgrade(config, "-1")
    engine = create_engine(use_test_database)
    try:
        assert "summaries" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        indexes = {ix["name"] for ix in inspect(engine).get_indexes("summaries")}
    finally:
        engine.dispose()

    assert {"ix_summaries_project_id", "uq_summaries_active_project"} <= indexes
