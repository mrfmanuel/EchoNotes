"""Project persistence (US-01..US-04) and the shared `updated_at` bump (US-02 AC3)."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.db.base import utcnow
from app.db.models import Project, Screenshot, Transcript
from app.errors import NotFoundError
from app.services.slugs import unique_slug

PROJECT_NOT_FOUND = "Project not found"
# Concurrent creates of the same name can collide on the unique slug; each retry re-reads
# the committed slugs, so a handful of attempts covers realistic concurrency.
MAX_SLUG_ATTEMPTS = 8

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectWithCounts:
    project: Project
    transcript_count: int
    screenshot_count: int


@dataclass(frozen=True)
class ProjectContents:
    transcripts: list[Transcript] = field(default_factory=list)
    screenshots: list[Screenshot] = field(default_factory=list)


def bump_updated_at(row: Project | Transcript) -> None:
    """Set `row.updated_at` to now, strictly later than before (coarse clocks on Windows)."""
    previous = row.updated_at
    now = utcnow()
    row.updated_at = (
        now if previous is None or now > previous else previous + timedelta(microseconds=1)
    )


async def touch_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Bump the parent project's `updated_at` in the caller's transaction (no commit).

    Call it whenever a transcript or screenshot is created, edited or deleted (US-02 AC3).
    """
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError(PROJECT_NOT_FOUND)
    bump_updated_at(project)


def _with_counts() -> Select[Any]:
    transcript_count = (
        select(func.count(Transcript.id))
        .where(Transcript.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )
    screenshot_count = (
        select(func.count(Screenshot.id))
        .where(Screenshot.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )
    return select(Project, transcript_count, screenshot_count)


async def list_projects(session: AsyncSession) -> list[ProjectWithCounts]:
    """All projects, most recently updated first (tie-break: newest created, then id)."""
    query = _with_counts().order_by(
        Project.updated_at.desc(), Project.created_at.desc(), Project.id.desc()
    )
    rows = (await session.execute(query)).all()
    return [ProjectWithCounts(project, int(tc), int(sc)) for project, tc, sc in rows]


async def get_project_with_counts(
    session: AsyncSession, project_id: uuid.UUID
) -> ProjectWithCounts:
    row = (await session.execute(_with_counts().where(Project.id == project_id))).first()
    if row is None:
        raise NotFoundError(PROJECT_NOT_FOUND)
    project, transcript_count, screenshot_count = row
    return ProjectWithCounts(project, int(transcript_count), int(screenshot_count))


async def list_transcript_summaries(
    session: AsyncSession, project_id: uuid.UUID
) -> list[Transcript]:
    """Transcripts of a project without loading `text`, newest first."""
    transcripts = await session.scalars(
        select(Transcript)
        .options(
            load_only(
                Transcript.id,
                Transcript.project_id,
                Transcript.title,
                Transcript.slug,
                Transcript.language,
                Transcript.duration_seconds,
                Transcript.provider,
                Transcript.created_at,
                Transcript.updated_at,
            )
        )
        .where(Transcript.project_id == project_id)
        .order_by(Transcript.created_at.desc(), Transcript.id.desc())
    )
    return list(transcripts.all())


async def get_project_contents(session: AsyncSession, project_id: uuid.UUID) -> ProjectContents:
    """Transcript summaries (no `text`) and screenshot metadata (no image bytes), newest first."""
    transcripts = await list_transcript_summaries(session, project_id)
    screenshots = await session.scalars(
        select(Screenshot)
        .where(Screenshot.project_id == project_id)
        .order_by(Screenshot.created_at.desc(), Screenshot.id.desc())
    )
    return ProjectContents(transcripts, list(screenshots.all()))


async def create_project(session: AsyncSession, name: str) -> ProjectWithCounts:
    """Insert a project with a unique slug, retrying if a concurrent insert took the slug."""
    for attempt in range(1, MAX_SLUG_ATTEMPTS + 1):
        slug = await unique_slug(session, Project.slug, name)
        project = Project(name=name, slug=slug)
        session.add(project)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            if attempt == MAX_SLUG_ATTEMPTS:
                raise
            logger.info("project slug collision, retrying", extra={"attempt": attempt})
            continue
        logger.info("project created", extra={"project_id": str(project.id)})
        return ProjectWithCounts(project, 0, 0)
    raise AssertionError("unreachable")  # pragma: no cover


async def rename_project(
    session: AsyncSession, project_id: uuid.UUID, name: str
) -> ProjectWithCounts:
    """Change the name only; the slug stays so export folder names are stable (US-03)."""
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError(PROJECT_NOT_FOUND)
    project.name = name
    bump_updated_at(project)
    await session.commit()
    return await get_project_with_counts(session, project_id)


async def delete_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Delete the project; the database cascades its transcripts and screenshots (US-04)."""
    result = await session.execute(delete(Project).where(Project.id == project_id))
    if result.rowcount == 0:  # type: ignore[attr-defined]
        await session.rollback()
        raise NotFoundError(PROJECT_NOT_FOUND)
    await session.commit()
    logger.info("project deleted", extra={"project_id": str(project_id)})
