"""JSON logs on stdout with the current request ID on every record.

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

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else came from `extra=` and is emitted as a field.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")
# HTTP client libraries log full URLs (with query strings) at INFO; keep only their warnings.
_QUIET_LOGGERS = ("httpx", "httpx2", "httpcore", "httpcore2")


class JsonFormatter(logging.Formatter):
    """Formats a record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, _exc, tb = record.exc_info
            payload["exc_type"] = exc_type.__name__
            payload["stack_trace"] = "".join(traceback.format_tb(tb))
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
