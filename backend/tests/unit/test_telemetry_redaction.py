"""#29 span redaction: the last line of defence before any span is exported."""

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.trace import Status, StatusCode

from app.telemetry.redaction import DENIED_SPAN_ATTRIBUTES, redact_span

PROJECT_ID = "4f1c9d7e-0000-4000-8000-000000000000"


def _span() -> ReadableSpan:
    return ReadableSpan(
        name="POST /api/projects/{projectId}/transcriptions",
        attributes={
            "http.route": "/api/projects/{projectId}/transcriptions",
            "http.response.status_code": 500,
            "url.query": "q=SECRET",
            "url.full": "http://x/api?q=SECRET",
            "client.address": "203.0.113.7",
            "user_agent.original": "Mozilla SECRET",
            "db.user": "SECRET-USER",
            "echonotes.project_id": PROJECT_ID,
        },
        events=[
            Event(
                "exception",
                {
                    "exception.type": "IntegrityError",
                    "exception.message": "SECRET parameters",
                    "exception.stacktrace": "Traceback ... SECRET",
                    "exception.escaped": "False",
                },
            )
        ],
        status=Status(StatusCode.ERROR, "IntegrityError: [parameters: ('SECRET',)]"),
    )


def test_redaction_drops_denied_attributes_and_keeps_safe_ones() -> None:
    redacted = redact_span(_span())

    assert dict(redacted.attributes or {}) == {
        "http.route": "/api/projects/{projectId}/transcriptions",
        "http.response.status_code": 500,
        "echonotes.project_id": PROJECT_ID,
    }


def test_redaction_keeps_only_the_exception_type_in_events() -> None:
    redacted = redact_span(_span())

    assert [(e.name, dict(e.attributes or {})) for e in redacted.events] == [
        ("exception", {"exception.type": "IntegrityError"})
    ]


def test_redaction_keeps_error_status_without_its_description() -> None:
    redacted = redact_span(_span())

    assert redacted.status.status_code is StatusCode.ERROR
    assert redacted.status.description is None
    assert "SECRET" not in redacted.to_json()


def test_denied_attributes_cover_urls_clients_exceptions_and_db_user() -> None:
    assert {
        "url.query",
        "url.full",
        "http.url",
        "http.target",
        "client.address",
        "user_agent.original",
        "exception.message",
        "exception.stacktrace",
        "db.user",
    } <= DENIED_SPAN_ATTRIBUTES
