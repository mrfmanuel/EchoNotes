"""Last line of defence for span privacy (#29, NFR-Privacy).

Our own spans only set safe attributes, but auto-instrumentation adds a few things that can
carry user data or connection details:

- exception events (`record_exception`) with `exception.message` / `exception.stacktrace`
  (the message, and the last stack-trace line, can echo user input);
- span status descriptions such as `"IntegrityError: ... [parameters: (...)]"`;
- query strings / full URLs, client addresses and user agents;
- the database user name.

`RedactingSpanProcessor` wraps the exporting processor and hands it a cleaned copy of every
finished span: denied attributes removed, exception events reduced to `exception.type`,
status descriptions dropped. IDs, sizes, durations, status codes, routes, provider names and
languages pass through.
"""

from collections.abc import Mapping

from opentelemetry.context import Context
from opentelemetry.sdk.trace import Event, ReadableSpan, Span, SpanProcessor
from opentelemetry.trace import Status
from opentelemetry.util.types import AttributeValue

DENIED_SPAN_ATTRIBUTES = frozenset(
    {
        "exception.message",
        "exception.stacktrace",
        "exception.escaped",
        "url.full",
        "url.query",
        "http.url",
        "http.target",
        "client.address",
        "client.port",
        "net.peer.ip",
        "http.client_ip",
        "user_agent.original",
        "http.user_agent",
        "db.user",
        "db.connection_string",
    }
)


def safe_attributes(
    attributes: Mapping[str, AttributeValue] | None,
) -> dict[str, AttributeValue]:
    return {k: v for k, v in (attributes or {}).items() if k not in DENIED_SPAN_ATTRIBUTES}


def redact_span(span: ReadableSpan) -> ReadableSpan:
    events = [
        Event(event.name, safe_attributes(event.attributes), event.timestamp)
        for event in span.events
    ]
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=safe_attributes(span.attributes),
        events=events,
        links=span.links,
        kind=span.kind,
        status=Status(span.status.status_code),  # no description
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingSpanProcessor(SpanProcessor):
    """Forwards to `delegate`, which only ever sees redacted copies of finished spans."""

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        self._delegate.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        self._delegate.on_end(redact_span(span))

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)
