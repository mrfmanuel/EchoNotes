"""Application errors rendered as the `Error` schema: `{"detail": "...", "code": "..."}`.

Request-validation 422s keep FastAPI's default `detail` list (docs/product-spec.md#341).
"""

from typing import Literal

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

ErrorCode = Literal[
    "not_found",
    "validation_error",
    "unsupported_media_type",
    "audio_too_large",
    "image_too_large",
    "provider_error",
    "provider_timeout",
]


class ApiError(Exception):
    """Raise from routers or services; rendered as `{"detail", "code"}` with `status_code`."""

    def __init__(self, status_code: int, detail: str, code: ErrorCode) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


class NotFoundError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, detail, "not_found")


async def _handle_api_error(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # pragma: no cover - registered for ApiError only
        raise exc
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail, "code": exc.code}
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
