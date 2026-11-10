"""Pluggable transcription (docs/architecture.md#transcriber-interface).

`TRANSCRIBER_PROVIDER` selects `fake` (deterministic, offline) or `groq` (Groq Whisper).
"""

from app.transcription.base import (
    ProviderError,
    ProviderTimeout,
    Transcriber,
    TranscriptionResult,
)
from app.transcription.factory import TranscriberConfigError, build_transcriber, get_transcriber

__all__ = [
    "ProviderError",
    "ProviderTimeout",
    "Transcriber",
    "TranscriberConfigError",
    "TranscriptionResult",
    "build_transcriber",
    "get_transcriber",
]
