"""Helpers to seed transcripts/screenshots directly through a session (no API yet: #12/#14)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Screenshot, Transcript

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def at(minute: int) -> datetime:
    """A fixed, timezone-aware timestamp; larger `minute` means later."""
    return datetime(2026, 1, 1, 12, minute, tzinfo=UTC)


async def add_transcript(
    session: AsyncSession,
    project_id: uuid.UUID,
    title: str = "Lecture",
    created_at: datetime | None = None,
) -> Transcript:
    transcript = Transcript(
        project_id=project_id,
        title=title,
        slug=title.lower(),
        text="secret transcript text",
        language="es",
        duration_seconds=12.5,
        provider="fake",
        source_filename="lecture.m4a",
    )
    if created_at is not None:
        transcript.created_at = created_at
    session.add(transcript)
    await session.commit()
    return transcript


async def add_screenshot(
    session: AsyncSession,
    project_id: uuid.UUID,
    transcript_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> Screenshot:
    screenshot = Screenshot(
        project_id=project_id,
        transcript_id=transcript_id,
        filename="slide.png",
        content_type="image/png",
        size_bytes=len(PNG_BYTES),
        data=PNG_BYTES,
    )
    if created_at is not None:
        screenshot.created_at = created_at
    session.add(screenshot)
    await session.commit()
    return screenshot


async def set_timestamps(
    session: AsyncSession, project_id: str, created_at: datetime, updated_at: datetime
) -> None:
    await session.execute(
        update(Project)
        .where(Project.id == uuid.UUID(project_id))
        .values(created_at=created_at, updated_at=updated_at)
    )
    await session.commit()
