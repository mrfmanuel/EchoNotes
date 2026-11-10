"""Groq Whisper transcriber (OpenAI-compatible `/audio/transcriptions` endpoint).

Privacy: logs and exception messages carry only the provider name, the HTTP status code and
the exception class. Never the API key, the filename, the audio or any response body.
"""

import logging
from typing import Any

import httpx2
from pydantic import SecretStr

from app.transcription.base import ProviderError, ProviderTimeout, TranscriptionResult

logger = logging.getLogger(__name__)

# Whisper `verbose_json` may report the language by name; the app stores ISO-639-1 codes.
LANGUAGE_NAMES = {"english": "en", "spanish": "es", "portuguese": "pt"}


def normalize_language(value: object, hint: str | None) -> str | None:
    """`english` → `en`, a 2-letter code is kept (lowercased), anything else → the hint."""
    if not isinstance(value, str):
        return hint
    cleaned = value.strip().lower()
    if cleaned in LANGUAGE_NAMES:
        return LANGUAGE_NAMES[cleaned]
    if len(cleaned) == 2 and cleaned.isalpha():
        return cleaned
    return hint


def _duration(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


class GroqTranscriber:
    name = "groq"

    def __init__(
        self,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport  # tests inject an `httpx2.MockTransport`

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, language: str | None
    ) -> TranscriptionResult:
        payload = await self._post(audio, filename, content_type, language)
        text = payload.get("text")
        if not isinstance(text, str):
            self._warn("transcription provider returned no text")
            raise ProviderError(self.name)
        return TranscriptionResult(
            text=text,
            language=normalize_language(payload.get("language"), language),
            duration_seconds=_duration(payload.get("duration")),
        )

    async def _post(
        self, audio: bytes, filename: str, content_type: str, language: str | None
    ) -> dict[str, Any]:
        data = {"model": self._model, "response_format": "verbose_json", "temperature": "0"}
        if language is not None:
            data["language"] = language
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        try:
            async with httpx2.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    self._url,
                    headers=headers,
                    data=data,
                    files={"file": (filename, audio, content_type)},
                )
        except httpx2.TimeoutException:
            self._warn("transcription provider timed out")
            raise ProviderTimeout(self.name) from None
        except httpx2.HTTPError as exc:
            self._warn("transcription provider unreachable", error_type=type(exc).__name__)
            raise ProviderError(self.name) from None
        return self._parse(response)

    def _parse(self, response: httpx2.Response) -> dict[str, Any]:
        if not response.is_success:
            self._warn("transcription provider error", status_code=response.status_code)
            raise ProviderError(self.name, response.status_code)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self._warn("transcription provider sent invalid JSON")
            raise ProviderError(self.name, response.status_code)
        return payload

    def _warn(self, message: str, **fields: object) -> None:
        logger.warning(message, extra={"provider": self.name, **fields})
