"""Telemetry for the key journey: upload audio -> transcript -> export (#29).

- `TranscriptionCreateRoute` wraps the WHOLE `POST /api/projects/{id}/transcriptions` handler
  (request validation included) in the `transcription.create` span and counts every request
  exactly once in `echonotes.transcriptions{provider, status}` plus the duration histogram,
  so request-validation 422s and unhandled bugs (500) are counted too.
- `annotate_transcription` lets the endpoint add safe attributes to that span.
- `track_export` wraps the ZIP build in the `export.build` span and `echonotes.exports{status}`.

Span attributes are safe only: IDs, sizes, counts, provider, language, status and the error
class name. Exception messages are never recorded (`record_exception=False`).
"""

import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from opentelemetry.trace import INVALID_SPAN, Span, Status, StatusCode
from opentelemetry.util.types import AttributeValue
from starlette.exceptions import HTTPException

from app.errors import ApiError
from app.telemetry.instruments import instruments

TRANSCRIPTION_SPAN = "transcription.create"
EXPORT_SPAN = "export.build"
UNKNOWN_PROVIDER = "unknown"

ATTR_PROJECT_ID = "echonotes.project_id"
ATTR_TRANSCRIPT_ID = "echonotes.transcript_id"
ATTR_AUDIO_SIZE = "echonotes.audio.size_bytes"
ATTR_PROVIDER = "echonotes.provider"
ATTR_LANGUAGE = "echonotes.language"
ATTR_STATUS = "echonotes.status"
ATTR_ERROR_TYPE = "error.type"


class TranscriptionStatus(StrEnum):
    SUCCESS = "success"
    CLIENT_ERROR = "client_error"  # 4xx: 404, 413, 415, 422
    PROVIDER_ERROR = "provider_error"  # 502
    TIMEOUT = "timeout"  # 504
    SERVER_ERROR = "server_error"  # any other 5xx / unexpected exception


FAILURE_STATUSES = frozenset(
    {
        TranscriptionStatus.PROVIDER_ERROR,
        TranscriptionStatus.TIMEOUT,
        TranscriptionStatus.SERVER_ERROR,
    }
)


def status_for_code(status_code: int) -> TranscriptionStatus:
    if status_code < 400:
        return TranscriptionStatus.SUCCESS
    if status_code == 502:
        return TranscriptionStatus.PROVIDER_ERROR
    if status_code == 504:
        return TranscriptionStatus.TIMEOUT
    if status_code < 500:
        return TranscriptionStatus.CLIENT_ERROR
    return TranscriptionStatus.SERVER_ERROR


def status_for_exception(exc: Exception) -> TranscriptionStatus:
    if isinstance(exc, RequestValidationError):
        return TranscriptionStatus.CLIENT_ERROR
    if isinstance(exc, ApiError | HTTPException):
        return status_for_code(exc.status_code)
    return TranscriptionStatus.SERVER_ERROR


@dataclass
class _Attempt:
    provider: str
    span: Span = INVALID_SPAN
    started: float = field(default_factory=time.perf_counter)


_current_attempt: ContextVar[_Attempt | None] = ContextVar("transcription_attempt", default=None)


def annotate_transcription(
    *,
    provider: str | None = None,
    project_id: uuid.UUID | None = None,
    transcript_id: uuid.UUID | None = None,
    size_bytes: int | None = None,
    language: str | None = None,
) -> None:
    """Add safe attributes to the current `transcription.create` span (no-op outside it)."""
    attempt = _current_attempt.get()
    if attempt is None:
        return
    if provider is not None:
        attempt.provider = provider
    values: dict[str, AttributeValue | None] = {
        ATTR_PROVIDER: provider,
        ATTR_PROJECT_ID: str(project_id) if project_id is not None else None,
        ATTR_TRANSCRIPT_ID: str(transcript_id) if transcript_id is not None else None,
        ATTR_AUDIO_SIZE: size_bytes,
        ATTR_LANGUAGE: language,
    }
    attempt.span.set_attributes({k: v for k, v in values.items() if v is not None})


def _finish(attempt: _Attempt, status: TranscriptionStatus, error_type: str | None) -> None:
    elapsed = time.perf_counter() - attempt.started
    span = attempt.span
    span.set_attribute(ATTR_PROVIDER, attempt.provider)
    span.set_attribute(ATTR_STATUS, status.value)
    if error_type is not None:
        span.set_attribute(ATTR_ERROR_TYPE, error_type)
    if status in FAILURE_STATUSES:
        span.set_status(Status(StatusCode.ERROR))
    labels = {"provider": attempt.provider, "status": status.value}
    tools = instruments()
    tools.transcriptions.add(1, labels)
    tools.transcription_duration.record(elapsed, labels)


def _default_provider(request: Request) -> str:
    name = getattr(getattr(request.app.state, "transcriber", None), "name", None)
    return name if isinstance(name, str) else UNKNOWN_PROVIDER


class TranscriptionCreateRoute(APIRoute):
    """Route class for the create-transcription endpoint only (see module docstring)."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def tracked_handler(request: Request) -> Response:
            attempt = _Attempt(provider=_default_provider(request))
            with instruments().tracer.start_as_current_span(
                TRANSCRIPTION_SPAN, record_exception=False, set_status_on_exception=False
            ) as span:
                attempt.span = span
                token = _current_attempt.set(attempt)
                try:
                    response = await handler(request)
                except Exception as exc:
                    _finish(attempt, status_for_exception(exc), type(exc).__name__)
                    raise
                finally:
                    _current_attempt.reset(token)
                status = status_for_code(response.status_code)
                error_type = (
                    None if status is TranscriptionStatus.SUCCESS else str(response.status_code)
                )
                _finish(attempt, status, error_type)
                return response

        return tracked_handler


@contextmanager
def track_export(project_id: uuid.UUID) -> Iterator[Span]:
    """`export.build` span + `echonotes.exports{status=success|error}` around a ZIP build."""
    tools = instruments()
    with tools.tracer.start_as_current_span(
        EXPORT_SPAN,
        attributes={ATTR_PROJECT_ID: str(project_id)},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.set_attribute(ATTR_STATUS, "error")
            span.set_attribute(ATTR_ERROR_TYPE, type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            tools.exports.add(1, {"status": "error"})
            raise
        span.set_attribute(ATTR_STATUS, "success")
        tools.exports.add(1, {"status": "success"})
