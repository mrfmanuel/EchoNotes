"""X-Request-ID handling and the single access log line per request."""

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_INTERNAL_ERROR_BODY = b'{"detail":"Internal Server Error"}'

access_logger = logging.getLogger("app.access")
error_logger = logging.getLogger("app.error")


def resolve_request_id(incoming: str | None) -> str:
    """Echo a well-formed incoming ID, otherwise generate a UUID4."""
    if incoming is not None and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return str(uuid.uuid4())


def _route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else scope.get("path", "")


class RequestContextMiddleware:
    """Pure ASGI middleware: sets the request ID contextvar, echoes the header on every
    response (including unhandled errors) and logs one access line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = dict(scope.get("headers", [])).get(REQUEST_ID_HEADER.lower().encode("latin-1"))
        request_id = resolve_request_id(raw.decode("latin-1") if raw is not None else None)
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            error_logger.exception("unhandled exception")
            if not response_started:
                await self._send_internal_error(send_with_request_id)
        finally:
            access_logger.info(
                "request completed",
                extra={
                    "method": scope.get("method"),
                    "route": _route_template(scope),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_var.reset(token)

    @staticmethod
    async def _send_internal_error(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_INTERNAL_ERROR_BODY)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _INTERNAL_ERROR_BODY})
