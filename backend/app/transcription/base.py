"""The `Transcriber` protocol, its result type and provider errors."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None
    duration_seconds: float | None


class Transcriber(Protocol):
    name: str

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, language: str | None
    ) -> TranscriptionResult: ...


class ProviderError(Exception):
    """The provider failed (non-2xx, connection error, malformed response). Maps to 502.

    The message carries only the provider name and the HTTP status code, never the API key,
    the audio, the filename or any response text.
    """

    def __init__(self, provider: str, status_code: int | None = None) -> None:
        self.provider = provider
        self.status_code = status_code
        suffix = f" (status {status_code})" if status_code is not None else ""
        super().__init__(f"{provider} transcription failed{suffix}")


class ProviderTimeout(Exception):
    """The provider did not answer within `TRANSCRIBE_TIMEOUT_SECONDS`. Maps to 504."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"{provider} transcription timed out")
