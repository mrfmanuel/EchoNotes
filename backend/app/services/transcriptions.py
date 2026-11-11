"""Transcripts: create from audio (US-05, US-07), read, edit (US-08) and delete (US-11).

Privacy (US-05 AC6, NFR-Privacy): the audio only lives in memory for the request, nothing
but IDs, sizes, durations, status and provider names is logged.
"""

import logging
import time
import uuid
from dataclasses import dataclass

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TRANSCRIPT_TITLE_MAX, Project, Transcript
from app.errors import ApiError, NotFoundError
from app.services.projects import (
    PROJECT_NOT_FOUND,
    bump_updated_at,
    list_transcript_summaries,
    touch_project,
)
from app.services.slugs import slugify
from app.services.uploads import basename, split_extension
from app.transcription import ProviderError, ProviderTimeout, Transcriber

TRANSCRIPT_SLUG_FALLBACK = "transcript"
TRANSCRIPT_NOT_FOUND = "Transcript not found"
UNTITLED = "Untitled"
SOURCE_FILENAME_MAX = 255

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioUpload:
    audio: bytes
    filename: str  # sent to the provider (always has a known extension)
    content_type: str
    source_filename: str | None  # what the client sent; stored, never logged


def default_title(filename: str | None) -> str:
    """The original filename without its extension, truncated; `Untitled` if empty."""
    stem, _extension = split_extension(basename(filename))
    return stem.strip()[:TRANSCRIPT_TITLE_MAX].strip() or UNTITLED


def resolve_title(title: str | None, filename: str | None) -> str:
    cleaned = (title or "").strip()
    return cleaned or default_title(filename)


async def ensure_project_exists(session: AsyncSession, project_id: uuid.UUID) -> None:
    """404 before any audio is read; ends the read transaction so no DB connection is held
    while the provider works."""
    project = await session.get(Project, project_id)
    await session.rollback()
    if project is None:
        raise NotFoundError(PROJECT_NOT_FOUND)


async def _transcribe(
    transcriber: Transcriber, upload: AudioUpload, language: str | None, project_id: uuid.UUID
) -> tuple[str, str | None, float | None]:
    started = time.perf_counter()
    log_fields: dict[str, object] = {
        "project_id": str(project_id),
        "provider": transcriber.name,
        "size_bytes": len(upload.audio),
    }
    try:
        result = await transcriber.transcribe(
            upload.audio, upload.filename, upload.content_type, language
        )
    except ProviderTimeout:
        logger.warning("transcription timed out", extra=log_fields)
        raise ApiError(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "The transcription provider timed out. Please try again.",
            "provider_timeout",
        ) from None
    except ProviderError as exc:
        logger.warning("transcription failed", extra={**log_fields, "status_code": exc.status_code})
        raise ApiError(
            status.HTTP_502_BAD_GATEWAY,
            "The transcription provider failed. Please try again.",
            "provider_error",
        ) from None
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    if result.duration_seconds is not None:
        # Real-time factor: seconds of processing per second of audio (lower is faster).
        log_fields["realtime_factor"] = round(elapsed_ms / 1000 / result.duration_seconds, 4)
    logger.info("transcription finished", extra={**log_fields, "transcribe_ms": elapsed_ms})
    return result.text, result.language or language, result.duration_seconds


async def create_transcript(
    session: AsyncSession,
    transcriber: Transcriber,
    project_id: uuid.UUID,
    upload: AudioUpload,
    title: str,
    language: str | None,
) -> Transcript:
    """Transcribe, then store the transcript and bump the project in one transaction.

    A provider failure raises before anything is written, so no transcript row is created.
    """
    text, stored_language, duration = await _transcribe(transcriber, upload, language, project_id)
    source = upload.source_filename[:SOURCE_FILENAME_MAX] if upload.source_filename else None
    transcript = Transcript(
        project_id=project_id,
        title=title,
        slug=slugify(title, TRANSCRIPT_SLUG_FALLBACK),
        text=text,
        language=stored_language,
        duration_seconds=duration,
        provider=transcriber.name,
        source_filename=source,
    )
    await touch_project(session, project_id)  # 404 if the project was deleted meanwhile
    session.add(transcript)
    await session.commit()
    logger.info(
        "transcript created",
        extra={
            "transcript_id": str(transcript.id),
            "project_id": str(project_id),
            "provider": transcriber.name,
            "size_bytes": len(upload.audio),
            "duration_seconds": duration,
        },
    )
    return transcript


async def list_transcripts(session: AsyncSession, project_id: uuid.UUID) -> list[Transcript]:
    """Summaries (no `text`) of a project's transcripts, newest first; 404 if unknown."""
    if await session.get(Project, project_id) is None:
        raise NotFoundError(PROJECT_NOT_FOUND)
    return await list_transcript_summaries(session, project_id)


async def get_transcript(session: AsyncSession, transcript_id: uuid.UUID) -> Transcript:
    transcript = await session.get(Transcript, transcript_id)
    if transcript is None:
        raise NotFoundError(TRANSCRIPT_NOT_FOUND)
    return transcript


async def update_transcript(
    session: AsyncSession,
    transcript_id: uuid.UUID,
    title: str | None = None,
    text: str | None = None,
) -> Transcript:
    """Edit the title (slug recomputed, US-10 AC5) and/or text; bump transcript and project."""
    transcript = await get_transcript(session, transcript_id)
    if title is not None:
        transcript.title = title
        transcript.slug = slugify(title, TRANSCRIPT_SLUG_FALLBACK)
    if text is not None:
        transcript.text = text
    bump_updated_at(transcript)
    await touch_project(session, transcript.project_id)
    await session.commit()
    logger.info(
        "transcript updated",
        extra={
            "transcript_id": str(transcript_id),
            "project_id": str(transcript.project_id),
            "title_changed": title is not None,
            "text_changed": text is not None,
        },
    )
    return transcript


async def delete_transcript(session: AsyncSession, transcript_id: uuid.UUID) -> None:
    """Delete; the FK (`ON DELETE SET NULL`) unlinks its screenshots, which stay (US-11)."""
    transcript = await get_transcript(session, transcript_id)
    project_id = transcript.project_id
    await session.delete(transcript)
    await touch_project(session, project_id)
    await session.commit()
    logger.info(
        "transcript deleted",
        extra={"transcript_id": str(transcript_id), "project_id": str(project_id)},
    )
