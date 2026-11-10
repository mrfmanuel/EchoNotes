"""Stub transcribers and upload helpers for the transcription tests (never the real Groq API)."""

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx2

from app.transcription import ProviderError, ProviderTimeout, TranscriptionResult

AUDIO = b"ID3" + b"\x00" * 32_000  # 32 003 bytes → fake duration 2.0 s


@dataclass
class RecordingTranscriber:
    """Records every call and returns a fixed result."""

    name: str = "stub"
    result: TranscriptionResult = TranscriptionResult("stub text", None, 1.5)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, language: str | None
    ) -> TranscriptionResult:
        self.calls.append(
            {
                "size": len(audio),
                "filename": filename,
                "content_type": content_type,
                "language": language,
            }
        )
        return self.result


@dataclass
class FailingTranscriber:
    """Raises the given provider exception."""

    error: Exception
    name: str = "stub"

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, language: str | None
    ) -> TranscriptionResult:
        raise self.error


def provider_error() -> FailingTranscriber:
    return FailingTranscriber(ProviderError("stub", 500))


def provider_timeout() -> FailingTranscriber:
    return FailingTranscriber(ProviderTimeout("stub"))


async def upload(
    client: httpx2.AsyncClient,
    project_id: uuid.UUID | str,
    filename: str = "lecture.m4a",
    audio: bytes = AUDIO,
    content_type: str = "audio/mp4",
    **form: str,
) -> httpx2.Response:
    return await client.post(
        f"/api/projects/{project_id}/transcriptions",
        files={"file": (filename, audio, content_type)},
        data=form,
    )
