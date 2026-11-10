"""#9 / #23: ON DELETE CASCADE and SET NULL on a real Postgres."""

import pytest
from sqlalchemy import delete, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Screenshot, Transcript

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def _seed(session: AsyncSession) -> tuple[Project, Transcript, Screenshot]:
    project = Project(name="Notes", slug="notes")
    transcript = Transcript(
        project=project, title="Lecture", slug="lecture", text="hi", provider="fake"
    )
    screenshot = Screenshot(
        project=project,
        transcript=transcript,
        filename="shot.png",
        content_type="image/png",
        size_bytes=4,
        data=b"\x89PNG",
    )
    session.add_all([project, transcript, screenshot])
    await session.commit()
    return project, transcript, screenshot


async def test_deleting_project_cascades_on_postgres(pg_session: AsyncSession) -> None:
    project, _, _ = await _seed(pg_session)

    await pg_session.execute(delete(Project).where(Project.id == project.id))
    await pg_session.commit()

    assert (await pg_session.execute(select(Transcript))).first() is None
    assert (await pg_session.execute(select(Screenshot))).first() is None


async def test_deleting_transcript_sets_screenshot_null_on_postgres(
    pg_session: AsyncSession,
) -> None:
    _, transcript, screenshot = await _seed(pg_session)
    screenshot_id = screenshot.id

    await pg_session.execute(delete(Transcript).where(Transcript.id == transcript.id))
    await pg_session.commit()
    pg_session.expire_all()

    remaining = await pg_session.get(Screenshot, screenshot_id)
    assert remaining is not None
    assert remaining.transcript_id is None


async def test_timestamps_are_timezone_aware_on_postgres(pg_session: AsyncSession) -> None:
    project, _, _ = await _seed(pg_session)
    await pg_session.refresh(project)

    assert project.created_at.tzinfo is not None
    assert project.updated_at.tzinfo is not None


async def test_listing_screenshots_does_not_load_data_on_postgres(
    pg_session: AsyncSession,
) -> None:
    project, _, _ = await _seed(pg_session)
    project_id = project.id
    pg_session.expire_all()

    listed = (
        await pg_session.scalars(select(Screenshot).where(Screenshot.project_id == project_id))
    ).all()

    assert len(listed) == 1
    assert "data" in inspect(listed[0]).unloaded
