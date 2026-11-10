"""Transcriptions endpoints (tag `transcriptions`): US-05/US-06 upload, US-07 language hint."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas
from app.config import get_settings
from app.db.models import TRANSCRIPT_TITLE_MAX
from app.db.session import get_session
from app.services import transcriptions as service
from app.services.uploads import MIB, read_capped, require_non_empty, resolve_audio_type
from app.transcription import Transcriber, get_transcriber

router = APIRouter(prefix="/api", tags=["transcriptions"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
TranscriberDep = Annotated[Transcriber, Depends(get_transcriber)]
ProjectIdPath = Annotated[uuid.UUID, Path(alias="projectId")]
LanguageHint = Literal["auto", "en", "es", "pt"]

_ERROR = {"model": schemas.Error}
CREATE_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {**_ERROR, "description": "Resource not found"},
    status.HTTP_413_CONTENT_TOO_LARGE: {**_ERROR, "description": "File too large"},
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {**_ERROR, "description": "File type not allowed"},
    status.HTTP_502_BAD_GATEWAY: {**_ERROR, "description": "Transcription provider error"},
    status.HTTP_504_GATEWAY_TIMEOUT: {**_ERROR, "description": "Transcription provider timeout"},
}


@router.post(
    "/projects/{projectId}/transcriptions",
    operation_id="createTranscription",
    status_code=status.HTTP_201_CREATED,
    response_model=schemas.Transcript,
    responses=CREATE_RESPONSES,
)
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
    try:
        await service.ensure_project_exists(session, project_id)
        audio_type = resolve_audio_type(file.filename, file.content_type)
        audio = require_non_empty(await read_capped(file, get_settings().max_audio_mb * MIB))
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
            language=None if language == "auto" else language,
        )
        return schemas.Transcript.model_validate(transcript)
    finally:
        # Drop every reference to the raw audio and release the spooled upload (US-05 AC6).
        audio = None
        upload = None
        await file.close()
