"""Builds the transcriber chosen by `TRANSCRIBER_PROVIDER` and exposes it as a dependency."""

from fastapi import Request

from app.config import Settings
from app.transcription.base import Transcriber
from app.transcription.fake import FakeTranscriber
from app.transcription.groq import GroqTranscriber


class TranscriberConfigError(RuntimeError):
    """Invalid transcription configuration; raised at startup so the app fails fast."""


def build_transcriber(settings: Settings) -> Transcriber:
    if settings.transcriber_provider == "fake":
        return FakeTranscriber()
    if not settings.groq_api_key.get_secret_value().strip():
        raise TranscriberConfigError(
            "GROQ_API_KEY must be set when TRANSCRIBER_PROVIDER=groq "
            "(or set TRANSCRIBER_PROVIDER=fake)"
        )
    return GroqTranscriber(
        api_key=settings.groq_api_key,
        base_url=settings.groq_base_url,
        model=settings.groq_model,
        timeout_seconds=settings.transcribe_timeout_seconds,
    )


def get_transcriber(request: Request) -> Transcriber:
    """FastAPI dependency; tests override it with stubs via `app.dependency_overrides`."""
    transcriber: Transcriber = request.app.state.transcriber
    return transcriber
