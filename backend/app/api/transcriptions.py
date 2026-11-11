"""Transcriptions endpoints (tag `transcriptions`).

US-05/US-06 upload, US-07 language hint, US-08 view/edit, US-10 download, US-11 delete.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas
from app.config import get_settings
from app.db.models import TRANSCRIPT_TITLE_MAX
from app.db.session import get_session
from app.services import transcriptions as service
from app.services.transcript_format import RenderableTranscript, render_markdown, render_text
from app.services.uploads import MIB, read_capped, require_non_empty, resolve_audio_type
from app.telemetry import TranscriptionCreateRoute, annotate_transcription
from app.transcription import Transcriber, get_transcriber

router = APIRouter(prefix="/api", tags=["transcriptions"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
TranscriberDep = Annotated[Transcriber, Depends(get_transcriber)]
ProjectIdPath = Annotated[uuid.UUID, Path(alias="projectId")]
TranscriptIdPath = Annotated[uuid.UUID, Path(alias="transcriptId")]
LanguageHint = Literal["auto", "en", "es", "pt"]
DownloadFormat = Literal["md", "txt"]

# Same renderers as the project export (#15), so downloads and export files are byte-identical.
DOWNLOAD_FORMATS: dict[str, tuple[Callable[[RenderableTranscript], str], str]] = {
    "md": (render_markdown, "text/markdown; charset=utf-8"),
    "txt": (render_text, "text/plain; charset=utf-8"),
}

_ERROR = {"model": schemas.Error}
NOT_FOUND: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {**_ERROR, "description": "Resource not found"},
}
CREATE_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {**_ERROR, "description": "Resource not found"},
    status.HTTP_413_CONTENT_TOO_LARGE: {**_ERROR, "description": "File too large"},
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {**_ERROR, "description": "File type not allowed"},
    status.HTTP_502_BAD_GATEWAY: {**_ERROR, "description": "Transcription provider error"},
    status.HTTP_504_GATEWAY_TIMEOUT: {**_ERROR, "description": "Transcription provider timeout"},
}


async def create_transcription(
    project_id: ProjectIdPath,
    session: SessionDep,
    transcriber: TranscriberDep,
    file: Annotated[UploadFile, File(description="Audio file")],
    language: Annotated[LanguageHint, Form()] = "auto",
    title: Annotated[str | None, Form(max_length=TRANSCRIPT_TITLE_MAX)] = None,
) -> schemas.Transcript:
    audio: bytes | None = None
    upload: service.AudioUpload | None = None
    hint = None if language == "auto" else language
    annotate_transcription(provider=transcriber.name, project_id=project_id, language=language)
    try:
        await service.ensure_project_exists(session, project_id)
        audio_type = resolve_audio_type(file.filename, file.content_type)
        audio = require_non_empty(await read_capped(file, get_settings().max_audio_mb * MIB))
        annotate_transcription(size_bytes=len(audio))
        upload = service.AudioUpload(
            audio=audio,
            filename=audio_type.filename,
            content_type=audio_type.content_type,
            source_filename=file.filename or None,
        )
        transcript = await service.create_transcript(
            session,
            transcriber,
            project_id,
            upload,
            title=service.resolve_title(title, file.filename),
            language=hint,
        )
        annotate_transcription(transcript_id=transcript.id)
        return schemas.Transcript.model_validate(transcript)
    finally:
        # Drop every reference to the raw audio and release the spooled upload (US-05 AC6).
        audio = None
        upload = None
        await file.close()


# Registered with its own route class: the whole create flow (request validation included) is
# one `transcription.create` span and one `echonotes.transcriptions` count (#29).
router.add_api_route(
    "/projects/{projectId}/transcriptions",
    create_transcription,
    methods=["POST"],
    operation_id="createTranscription",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Transcript,
    responses=CREATE_RESPONSES,
    route_class_override=TranscriptionCreateRoute,
)


@router.get(
    "/projects/{projectId}/transcriptions",
    operation_id="listTranscriptions",
    response_model=list[schemas.TranscriptSummary],
    responses=NOT_FOUND,
)
async def list_transcriptions(
    project_id: ProjectIdPath, session: SessionDep
) -> list[schemas.TranscriptSummary]:
    transcripts = await service.list_transcripts(session, project_id)
    return [schemas.TranscriptSummary.model_validate(t) for t in transcripts]


@router.get(
    "/transcriptions/{transcriptId}",
    operation_id="getTranscription",
    response_model=schemas.Transcript,
    responses=NOT_FOUND,
)
async def get_transcription(
    transcript_id: TranscriptIdPath, session: SessionDep
) -> schemas.Transcript:
    return schemas.Transcript.model_validate(await service.get_transcript(session, transcript_id))


@router.patch(
    "/transcriptions/{transcriptId}",
    operation_id="updateTranscription",
    response_model=schemas.Transcript,
    responses=NOT_FOUND,
)
async def update_transcription(
    transcript_id: TranscriptIdPath, body: schemas.TranscriptUpdate, session: SessionDep
) -> schemas.Transcript:
    transcript = await service.update_transcript(
        session, transcript_id, title=body.title, text=body.text
    )
    return schemas.Transcript.model_validate(transcript)


@router.delete(
    "/transcriptions/{transcriptId}",
    operation_id="deleteTranscription",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=NOT_FOUND,
)
async def delete_transcription(transcript_id: TranscriptIdPath, session: SessionDep) -> Response:
    await service.delete_transcript(session, transcript_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/transcriptions/{transcriptId}/download",
    operation_id="downloadTranscription",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "description": "File attachment",
            "content": {"text/markdown": {}, "text/plain": {}},
        },
        **NOT_FOUND,
    },
)
async def download_transcription(
    transcript_id: TranscriptIdPath,
    download_format: Annotated[DownloadFormat, Query(alias="format")],
    session: SessionDep,
) -> Response:
    transcript = await service.get_transcript(session, transcript_id)
    render, media_type = DOWNLOAD_FORMATS[download_format]
    logger.info(
        "transcript downloaded",
        extra={"transcript_id": str(transcript_id), "format": download_format},
    )
    return Response(
        content=render(transcript).encode("utf-8"),
        media_type=media_type,
        headers={
            # Slugs are ASCII-only (`slugify`), so a plain quoted filename is always valid.
            "Content-Disposition": f'attachment; filename="{transcript.slug}.{download_format}"',
        },
    )
