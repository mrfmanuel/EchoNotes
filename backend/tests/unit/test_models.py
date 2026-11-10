"""#9 model acceptance criteria on SQLite (foreign keys enabled)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import String, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Screenshot, Transcript

pytestmark = pytest.mark.anyio


def _project(slug: str = "notes") -> Project:
    return Project(name="Notes", slug=slug)


def _transcript(project: Project) -> Transcript:
    return Transcript(project=project, title="Lecture", slug="lecture", text="hi", provider="fake")


def _screenshot(project: Project, transcript: Transcript | None = None) -> Screenshot:
    return Screenshot(
        project=project,
        transcript=transcript,
        filename="shot.png",
        content_type="image/png",
        size_bytes=4,
        data=b"\x89PNG",
    )


async def test_sqlite_foreign_keys_are_enabled(session: AsyncSession) -> None:
    assert (await session.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1


async def test_models_have_uuid_primary_keys_and_tz_aware_timestamps(
    session: AsyncSession,
) -> None:
    project = _project()
    transcript = _transcript(project)
    screenshot = _screenshot(project, transcript)
    session.add_all([project, transcript, screenshot])
    await session.commit()
    session.expire_all()

    for row in (project, transcript, screenshot):
        await session.refresh(row)
        assert isinstance(row.id, uuid.UUID)
        assert row.created_at.tzinfo is not None
        assert row.created_at.utcoffset() == timedelta(0)
    assert project.updated_at.tzinfo is not None
    assert transcript.updated_at.tzinfo is not None


async def test_updated_at_is_refreshed_on_update(session: AsyncSession) -> None:
    project = _project()
    session.add(project)
    await session.commit()
    old = datetime(2020, 1, 1, tzinfo=UTC)
    project.updated_at = old
    await session.commit()

    project.name = "Renamed"
    await session.commit()
    await session.refresh(project)

    assert project.updated_at > old


async def test_project_slug_is_unique(session: AsyncSession) -> None:
    session.add_all([_project("same"), _project("same")])

    with pytest.raises(IntegrityError):
        await session.commit()


def test_name_and_title_length_limits() -> None:
    name_type = Project.__table__.c.name.type
    title_type = Transcript.__table__.c.title.type
    assert isinstance(name_type, String) and name_type.length == 100
    assert isinstance(title_type, String) and title_type.length == 200


async def test_deleting_project_cascades_to_transcripts_and_screenshots(
    session: AsyncSession,
) -> None:
    # Given a project with a transcript and a screenshot
    project = _project()
    transcript = _transcript(project)
    session.add_all([project, transcript, _screenshot(project, transcript)])
    await session.commit()

    # When the project is deleted (at the database level, ON DELETE CASCADE)
    await session.execute(delete(Project).where(Project.id == project.id))
    await session.commit()

    # Then both rows are gone
    assert (await session.execute(select(Transcript))).first() is None
    assert (await session.execute(select(Screenshot))).first() is None


async def test_deleting_transcript_sets_screenshot_transcript_id_null(
    session: AsyncSession,
) -> None:
    # Given a screenshot linked to a transcript
    project = _project()
    transcript = _transcript(project)
    screenshot = _screenshot(project, transcript)
    session.add_all([project, transcript, screenshot])
    await session.commit()
    screenshot_id = screenshot.id

    # When the transcript is deleted
    await session.execute(delete(Transcript).where(Transcript.id == transcript.id))
    await session.commit()
    session.expire_all()

    # Then the screenshot remains with transcript_id = NULL
    remaining = await session.get(Screenshot, screenshot_id)
    assert remaining is not None
    assert remaining.transcript_id is None


async def test_listing_screenshots_does_not_load_image_data(session: AsyncSession) -> None:
    project = _project()
    session.add_all([project, _screenshot(project), _screenshot(project)])
    await session.commit()
    project_id = project.id
    session.expire_all()

    listed = (
        await session.scalars(select(Screenshot).where(Screenshot.project_id == project_id))
    ).all()

    assert len(listed) == 2
    for screenshot in listed:
        assert "data" in inspect(screenshot).unloaded
        assert screenshot.filename == "shot.png"
