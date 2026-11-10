"""Screenshot persistence (US-12, US-14, US-15). Image bytes live in `screenshot.data` (bytea)."""

import logging
import uuid
from dataclasses import dataclass

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.db.models import Project, Screenshot, Transcript
from app.errors import ApiError, NotFoundError
from app.services.projects import PROJECT_NOT_FOUND, touch_project

SCREENSHOT_NOT_FOUND = "Screenshot not found"
TRANSCRIPT_NOT_IN_PROJECT = "transcript_id must be a transcript of the same project"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NewScreenshot:
    filename: str
    content_type: str
    data: bytes
    transcript_id: uuid.UUID | None = None


async def ensure_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    if await session.get(Project, project_id) is None:
        raise NotFoundError(PROJECT_NOT_FOUND)


async def ensure_transcript_in_project(
    session: AsyncSession, project_id: uuid.UUID, transcript_id: uuid.UUID
) -> None:
    """422 `validation_error` if the transcript is unknown or belongs to another project."""
    owner = await session.scalar(
        select(Transcript.project_id).where(Transcript.id == transcript_id)
    )
    if owner != project_id:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, TRANSCRIPT_NOT_IN_PROJECT, "validation_error"
        )


async def list_screenshots(session: AsyncSession, project_id: uuid.UUID) -> list[Screenshot]:
    """Metadata only (`data` stays deferred), oldest first."""
    await ensure_project(session, project_id)
    result = await session.scalars(
        select(Screenshot)
        .where(Screenshot.project_id == project_id)
        .order_by(Screenshot.created_at.asc(), Screenshot.id.asc())
    )
    return list(result.all())


async def create_screenshot(
    session: AsyncSession, project_id: uuid.UUID, new: NewScreenshot
) -> Screenshot:
    await ensure_project(session, project_id)
    if new.transcript_id is not None:
        await ensure_transcript_in_project(session, project_id, new.transcript_id)
    screenshot = Screenshot(
        project_id=project_id,
        transcript_id=new.transcript_id,
        filename=new.filename,
        content_type=new.content_type,
        size_bytes=len(new.data),
        data=new.data,
    )
    session.add(screenshot)
    await touch_project(session, project_id)
    await session.commit()
    logger.info(
        "screenshot uploaded",
        extra={
            "screenshot_id": str(screenshot.id),
            "project_id": str(project_id),
            "size_bytes": screenshot.size_bytes,
            "content_type": screenshot.content_type,
        },
    )
    return screenshot


async def get_screenshot(session: AsyncSession, screenshot_id: uuid.UUID) -> Screenshot:
    screenshot = await session.get(Screenshot, screenshot_id)
    if screenshot is None:
        raise NotFoundError(SCREENSHOT_NOT_FOUND)
    return screenshot


async def get_image(session: AsyncSession, screenshot_id: uuid.UUID) -> tuple[bytes, str]:
    """The stored bytes and their content type."""
    screenshot = await session.scalar(
        select(Screenshot).options(undefer(Screenshot.data)).where(Screenshot.id == screenshot_id)
    )
    if screenshot is None:
        raise NotFoundError(SCREENSHOT_NOT_FOUND)
    return screenshot.data, screenshot.content_type


async def link_screenshot(
    session: AsyncSession, screenshot_id: uuid.UUID, transcript_id: uuid.UUID | None
) -> Screenshot:
    """Link to a transcript of the same project, or unlink with `None` (US-14)."""
    screenshot = await get_screenshot(session, screenshot_id)
    if transcript_id is not None:
        await ensure_transcript_in_project(session, screenshot.project_id, transcript_id)
    screenshot.transcript_id = transcript_id
    await touch_project(session, screenshot.project_id)
    await session.commit()
    logger.info(
        "screenshot link updated",
        extra={"screenshot_id": str(screenshot_id), "linked": transcript_id is not None},
    )
    return screenshot


async def delete_screenshot(session: AsyncSession, screenshot_id: uuid.UUID) -> None:
    screenshot = await get_screenshot(session, screenshot_id)
    project_id = screenshot.project_id
    await session.delete(screenshot)
    await touch_project(session, project_id)
    await session.commit()
    logger.info(
        "screenshot deleted",
        extra={"screenshot_id": str(screenshot_id), "project_id": str(project_id)},
    )
