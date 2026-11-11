"""OTLP log export: the same safe fields as the stdout JSON lines, plus the trace context.

A small handler on the root logger instead of the SDK's `LoggingHandler` (deprecated in
opentelemetry-sdk 1.45), because that one attaches `exception.message` and the full
formatted exception, which can echo user input. Here the body is the log message and the
attributes are exactly `app.logging.safe_fields` (request ID, `extra=` fields, exception class
and stack frames). The active span context is attached, so Loki lines link to Tempo traces.
"""

import logging
import time

from opentelemetry import context as otel_context
from opentelemetry._logs import Logger, LoggerProvider, SeverityNumber
from opentelemetry.util.types import AttributeValue

from app.logging import safe_fields

# The exporters log their own failures; exporting those would loop.
_SKIPPED_LOGGER_PREFIXES = ("opentelemetry",)
_SEVERITY = (
    (logging.CRITICAL, SeverityNumber.FATAL, "FATAL"),
    (logging.ERROR, SeverityNumber.ERROR, "ERROR"),
    (logging.WARNING, SeverityNumber.WARN, "WARN"),
    (logging.INFO, SeverityNumber.INFO, "INFO"),
    (logging.DEBUG, SeverityNumber.DEBUG, "DEBUG"),
)
_PRIMITIVES = (str, bool, int, float)


def severity(levelno: int) -> tuple[SeverityNumber, str]:
    for threshold, number, text in _SEVERITY:
        if levelno >= threshold:
            return number, text
    return SeverityNumber.TRACE, "TRACE"


def otlp_attributes(record: logging.LogRecord) -> dict[str, AttributeValue]:
    """`safe_fields` as OTLP attributes: `None` dropped, non-primitives stringified."""
    attributes: dict[str, AttributeValue] = {"logger": record.name}
    for key, value in safe_fields(record).items():
        if value is None:
            continue
        attributes[key] = value if isinstance(value, _PRIMITIVES) else str(value)
    return attributes


class OtlpLogHandler(logging.Handler):
    def __init__(self, logger_provider: LoggerProvider) -> None:
        super().__init__()
        self._provider = logger_provider
        self._loggers: dict[str, Logger] = {}

    def _logger(self, name: str) -> Logger:
        logger = self._loggers.get(name)
        if logger is None:
            logger = self._loggers[name] = self._provider.get_logger(name)
        return logger

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_SKIPPED_LOGGER_PREFIXES):
            return
        try:
            number, text = severity(record.levelno)
            self._logger(record.name).emit(
                timestamp=int(record.created * 1e9),
                observed_timestamp=time.time_ns(),
                context=otel_context.get_current(),
                severity_number=number,
                severity_text=text,
                body=record.getMessage(),
                attributes=otlp_attributes(record),
            )
        except Exception:
            self.handleError(record)
