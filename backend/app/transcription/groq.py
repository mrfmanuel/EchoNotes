"""Groq Whisper transcriber (OpenAI-compatible `/audio/transcriptions` endpoint).

Privacy: logs and exception messages carry only the provider name, the HTTP status code and
the exception class. Never the API key, the filename, the audio or any response body.

Tracing (#29): there is no OpenTelemetry instrumentation for `httpx2`, so the provider call
is wrapped in a manual CLIENT span `groq.transcribe` with safe attributes only (HTTP method,
server address, status code, audio size, duration and `error.type`).
"""

import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx2
from opentelemetry.trace import SpanKind, Status, StatusCode, get_current_span
from pydantic import SecretStr

from app.telemetry import instruments
from app.transcription.base import ProviderError, ProviderTimeout, TranscriptionResult

logger = logging.getLogger(__name__)

GROQ_SPAN = "groq.transcribe"

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
        self._host = urlsplit(self._url).hostname or ""
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport  # tests inject an `httpx2.MockTransport`

    async def transcribe(
        self, audio: bytes, filename: str, content_type: str, language: str | None
    ) -> TranscriptionResult:
        started = time.perf_counter()
        with instruments().tracer.start_as_current_span(
            GROQ_SPAN,
            kind=SpanKind.CLIENT,
            attributes={
                "echonotes.provider": self.name,
                "http.request.method": "POST",
                "server.address": self._host,
                "echonotes.audio.size_bytes": len(audio),
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                return await self._transcribe(audio, filename, content_type, language)
            except (ProviderError, ProviderTimeout):
                raise  # already marked with the precise error type
            except Exception as exc:
                _mark_error(type(exc).__name__)
                raise
            finally:
                span.set_attribute(
                    "echonotes.duration_ms", round((time.perf_counter() - started) * 1000, 2)
                )

    async def _transcribe(
        self, audio: bytes, filename: str, content_type: str, language: str | None
    ) -> TranscriptionResult:
        payload = await self._post(audio, filename, content_type, language)
        text = payload.get("text")
        if not isinstance(text, str):
            self._warn("transcription provider returned no text")
            _mark_error("invalid_response")
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
        except httpx2.TimeoutException as exc:
            self._warn("transcription provider timed out")
            _mark_error(type(exc).__name__)
            raise ProviderTimeout(self.name) from None
        except httpx2.HTTPError as exc:
            self._warn("transcription provider unreachable", error_type=type(exc).__name__)
            _mark_error(type(exc).__name__)
            raise ProviderError(self.name) from None
        get_current_span().set_attribute("http.response.status_code", response.status_code)
        return self._parse(response)

    def _parse(self, response: httpx2.Response) -> dict[str, Any]:
        if not response.is_success:
            self._warn("transcription provider error", status_code=response.status_code)
            _mark_error(str(response.status_code))
            raise ProviderError(self.name, response.status_code)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self._warn("transcription provider sent invalid JSON")
            _mark_error("invalid_response")
            raise ProviderError(self.name, response.status_code)
        return payload

    def _warn(self, message: str, **fields: object) -> None:
        logger.warning(message, extra={"provider": self.name, **fields})


def _mark_error(error_type: str) -> None:
    """Mark the current `groq.transcribe` span failed: class name or status code, no message."""
    span = get_current_span()
    span.set_attribute("error.type", error_type)
    span.set_status(Status(StatusCode.ERROR))
