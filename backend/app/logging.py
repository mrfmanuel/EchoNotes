"""JSON logs on stdout with the current request ID on every record.

Every line also carries `trace_id` (32 hex) and `span_id` (16 hex) of the active span, both
`null` when no span is active (#29). With telemetry on, the same safe fields are exported over
OTLP as well (`app.telemetry.logs`).

Privacy: never pass transcript text, titles, filenames, bodies, query strings, bytes,
API keys or database URLs to a logger. Exception records keep the class and the stack
frames but not the exception message, which could echo user input.
"""

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

from opentelemetry import trace

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else came from `extra=` and is emitted as a field.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)
# Extras never emitted: uvicorn's `color_message` duplicates `message` with ANSI escapes (#41).
_DROPPED_EXTRAS = frozenset({"color_message"})
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")
# HTTP client libraries log full URLs (with query strings) at INFO; keep only their warnings.
# urllib3 is used by the OTLP exporters; its debug lines name hosts and are pure noise.
_QUIET_LOGGERS = ("httpx", "httpx2", "httpcore", "httpcore2", "urllib3")
_BASE_FIELDS = frozenset({"timestamp", "level", "logger", "message"})


def current_trace_ids() -> dict[str, str | None]:
    """`trace_id`/`span_id` of the active span as lowercase hex; both `None` if none is active
    (outside a request, or always while telemetry is off)."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {"trace_id": None, "span_id": None}
    return {
        "trace_id": format(context.trace_id, "032x"),
        "span_id": format(context.span_id, "016x"),
    }


def safe_fields(record: logging.LogRecord) -> dict[str, Any]:
    """The request ID, the `extra=` fields and the exception class + stack frames.

    Shared by the stdout JSON lines and the OTLP log export so both carry the same fields.
    The exception message is never included: it could echo user input.
    """
    fields: dict[str, Any] = {"request_id": request_id_var.get()}
    for key, value in vars(record).items():
        if key in _STANDARD_ATTRS or key in _DROPPED_EXTRAS or key in _BASE_FIELDS:
            continue
        fields.setdefault(key, value)
    if record.exc_info and record.exc_info[0] is not None:
        exc_type, _exc, tb = record.exc_info
        fields["exc_type"] = exc_type.__name__
        fields["stack_trace"] = "".join(traceback.format_tb(tb))
    return fields


class JsonFormatter(logging.Formatter):
    """Formats a record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = safe_fields(record)
        payload["request_id"] = fields.pop("request_id")
        payload.update(current_trace_ids())
        for key, value in fields.items():
            payload.setdefault(key, value)
        return json.dumps(payload, default=str)


class StdoutHandler(logging.StreamHandler[TextIO]):
    """Writes to whatever `sys.stdout` is at emit time (keeps working under test capture)."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property  # type: ignore[override]
    def stream(self) -> TextIO:
        return sys.stdout

    @stream.setter
    def stream(self, _value: TextIO) -> None:
        pass


def configure_logging(level: str) -> None:
    """Route the root, app and uvicorn loggers through one JSON handler on stdout.

    Uvicorn's own access log is disabled; `RequestContextMiddleware` writes one access line.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, StdoutHandler):
            root.removeHandler(handler)
    handler = StdoutHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)

    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.setLevel(logging.NOTSET)
        logger.propagate = True

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
