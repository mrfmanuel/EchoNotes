"""Deterministic offline transcriber for local development, tests and CI."""

from app.transcription.base import TranscriptionResult

FAKE_BYTES_PER_SECOND = 16000  # about 128 kbps
FAKE_DEFAULT_LANGUAGE = "en"


class FakeTranscriber:
    name = "fake"

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, language: str | None
    ) -> TranscriptionResult:
        size = len(audio)
        return TranscriptionResult(
            text=f"[fake transcript] {filename} ({size} bytes)",
            language=language or FAKE_DEFAULT_LANGUAGE,
            duration_seconds=round(size / FAKE_BYTES_PER_SECOND, 2),
        )
