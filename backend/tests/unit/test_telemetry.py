"""#29 OpenTelemetry on the key journey: spans, metrics and logs sharing a trace ID.

Everything is exported to in-memory exporters (`tests.telemetry_utils.Capture`); no collector,
no network, fake/stub transcribers and `httpx2.MockTransport` only.
"""

import logging
import threading
import uuid
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import httpx2
import pytest
from fastapi import FastAPI
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.telemetry.instruments import NOOP_INSTRUMENTS, instruments
from app.telemetry.journey import TranscriptionStatus, status_for_code
from app.telemetry.logs import OtlpLogHandler
from app.telemetry.setup import TelemetryRuntime, build_resource, otlp_endpoints
from app.transcription import Transcriber, get_transcriber
from app.transcription.groq import GroqTranscriber
from tests.log_utils import parse_json_logs
from tests.telemetry_utils import Capture
from tests.transcription_utils import (
    AUDIO,
    FailingTranscriber,
    provider_error,
    provider_timeout,
    upload,
)

pytestmark = pytest.mark.anyio

TRANSCRIPTIONS = "echonotes.transcriptions"
DURATION = "echonotes.transcription.duration"
EXPORTS = "echonotes.exports"
CREATE_ROUTE = "/api/projects/{projectId}/transcriptions"


def _use(app: FastAPI, transcriber: Transcriber) -> None:
    app.dependency_overrides[get_transcriber] = lambda: transcriber


async def _project(client: httpx2.AsyncClient) -> dict[str, Any]:
    response = await client.post("/api/projects", json={"name": "Telemetry"})
    assert response.status_code == 201
    return response.json()


def _groq(handler: Any) -> GroqTranscriber:
    return GroqTranscriber(
        api_key=SecretStr("gsk_test_key"),
        base_url="https://api.groq.example/openai/v1",
        model="whisper-large-v3-turbo",
        timeout_seconds=5,
        transport=httpx2.MockTransport(handler),
    )


class Boom(RuntimeError):
    """An unexpected bug inside the transcription flow."""


# --- Status classification ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (201, "success"),
        (404, "client_error"),
        (413, "client_error"),
        (415, "client_error"),
        (422, "client_error"),
        (502, "provider_error"),
        (504, "timeout"),
        (500, "server_error"),
        (503, "server_error"),
    ],
)
def test_status_for_code_maps_http_status_to_metric_status(code: int, expected: str) -> None:
    assert status_for_code(code) == TranscriptionStatus(expected)


# --- Metrics -------------------------------------------------------------------------------


async def test_successful_transcription_is_counted_once_with_provider_and_status(
    telemetry: Capture, client: httpx2.AsyncClient
) -> None:
    project = await _project(client)

    response = await upload(client, project["id"])

    assert response.status_code == 201
    assert telemetry.counts(TRANSCRIPTIONS) == {(("provider", "fake"), ("status", "success")): 1}
    assert telemetry.counts(DURATION) == {(("provider", "fake"), ("status", "success")): 1}


@pytest.mark.parametrize(
    ("transcriber", "kwargs", "http_status", "metric_status"),
    [
        (None, {"filename": "notes.pdf", "content_type": "application/pdf"}, 415, "client_error"),
        (None, {"language": "xx"}, 422, "client_error"),  # rejected by request validation
        (None, {"audio": b""}, 422, "client_error"),
        (provider_error(), {}, 502, "provider_error"),
        (provider_timeout(), {}, 504, "timeout"),
        (FailingTranscriber(Boom("unexpected")), {}, 500, "server_error"),
    ],
    ids=["415", "422-validation", "422-empty", "502", "504", "500-unhandled"],
)
async def test_every_outcome_is_counted_once_with_its_status(
    telemetry: Capture,
    app: FastAPI,
    client: httpx2.AsyncClient,
    transcriber: Transcriber | None,
    kwargs: dict[str, Any],
    http_status: int,
    metric_status: str,
) -> None:
    if transcriber is not None:
        _use(app, transcriber)
    provider = transcriber.name if transcriber is not None else "fake"
    project = await _project(client)

    response = await upload(client, project["id"], **kwargs)

    assert response.status_code == http_status
    labels = (("provider", provider), ("status", metric_status))
    assert telemetry.counts(TRANSCRIPTIONS) == {labels: 1}
    assert telemetry.counts(DURATION) == {labels: 1}


async def test_unknown_project_counts_as_client_error(
    telemetry: Capture, client: httpx2.AsyncClient
) -> None:
    response = await upload(client, uuid.uuid4())

    assert response.status_code == 404
    assert telemetry.counts(TRANSCRIPTIONS) == {
        (("provider", "fake"), ("status", "client_error")): 1
    }


async def test_other_endpoints_are_not_counted_as_transcriptions(
    telemetry: Capture, client: httpx2.AsyncClient
) -> None:
    project = await _project(client)
    await client.get(f"/api/projects/{project['id']}/transcriptions")

    assert telemetry.points(TRANSCRIPTIONS) == []


async def test_export_is_counted_as_success_or_error(
    telemetry: Capture, client: httpx2.AsyncClient
) -> None:
    project = await _project(client)

    assert (await client.get(f"/api/projects/{project['id']}/export")).status_code == 200
    assert (await client.get(f"/api/projects/{uuid.uuid4()}/export")).status_code == 404

    assert telemetry.counts(EXPORTS) == {(("status", "success"),): 1, (("status", "error"),): 1}


async def test_http_server_metrics_use_route_templates(
    telemetry: Capture, client: httpx2.AsyncClient
) -> None:
    project = await _project(client)
    await upload(client, project["id"])

    assert "http.server.request.duration" in telemetry.metric_names()
    routes = {
        attrs.get("http.route") for attrs, _ in telemetry.points("http.server.request.duration")
    }
    assert CREATE_ROUTE in routes
    assert not any(project["id"] in str(route) for route in routes)


# --- Traces --------------------------------------------------------------------------------


async def test_transcription_span_has_safe_attributes_inside_the_server_span(
    telemetry: Capture, client: httpx2.AsyncClient
) -> None:
    project = await _project(client)

    created = (await upload(client, project["id"], language="es")).json()

    span = telemetry.span("transcription.create")
    assert span.attributes is not None
    assert dict(span.attributes) == {
        "echonotes.provider": "fake",
        "echonotes.project_id": project["id"],
        "echonotes.language": "es",
        "echonotes.audio.size_bytes": len(AUDIO),
        "echonotes.transcript_id": created["id"],
        "echonotes.status": "success",
    }
    server = telemetry.span(f"POST {CREATE_ROUTE}")
    assert server.kind is SpanKind.SERVER
    assert span.parent is not None and span.parent.span_id == server.context.span_id
    db_spans = [s for s in telemetry.spans() if s.attributes and "db.statement" in s.attributes]
    assert any(s.context.trace_id == server.context.trace_id for s in db_spans)


async def test_failed_transcription_span_is_error_with_class_name_only(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    _use(app, FailingTranscriber(Boom("unexpected")))
    project = await _project(client)

    await upload(client, project["id"])

    span = telemetry.span("transcription.create")
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description is None
    assert span.attributes is not None
    assert span.attributes["error.type"] == "Boom"
    assert span.attributes["echonotes.status"] == "server_error"
    assert span.events == ()


async def test_export_span_has_counts_and_size(
    telemetry: Capture, client: httpx2.AsyncClient
) -> None:
    project = await _project(client)
    await upload(client, project["id"])

    response = await client.get(f"/api/projects/{project['id']}/export")

    span = telemetry.span("export.build")
    assert span.attributes is not None
    assert span.attributes["echonotes.project_id"] == project["id"]
    assert span.attributes["echonotes.transcript_count"] == 1
    assert span.attributes["echonotes.screenshot_count"] == 0
    assert span.attributes["echonotes.export.size_bytes"] == len(response.content)
    assert span.attributes["echonotes.status"] == "success"


async def test_groq_call_is_a_client_span_with_status_code(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    _use(app, _groq(lambda _r: httpx2.Response(200, json={"text": "hola", "language": "es"})))
    project = await _project(client)

    assert (await upload(client, project["id"])).status_code == 201

    span = telemetry.span("groq.transcribe")
    assert span.kind is SpanKind.CLIENT
    assert span.attributes is not None
    assert span.attributes["http.response.status_code"] == 200
    assert span.attributes["server.address"] == "api.groq.example"
    assert span.attributes["echonotes.audio.size_bytes"] == len(AUDIO)
    assert span.attributes["echonotes.duration_ms"] >= 0
    assert span.parent is not None
    assert span.parent.span_id == telemetry.span("transcription.create").context.span_id


@pytest.mark.parametrize(
    ("handler", "error_type", "metric_status"),
    [
        (lambda _r: httpx2.Response(500, json={"error": "x"}), "500", "provider_error"),
        (lambda _r: httpx2.Response(200, text="not json"), "invalid_response", "provider_error"),
        (
            lambda r: (_ for _ in ()).throw(httpx2.ReadTimeout("t", request=r)),
            "ReadTimeout",
            "timeout",
        ),
        (
            lambda r: (_ for _ in ()).throw(httpx2.ConnectError("c", request=r)),
            "ConnectError",
            "provider_error",
        ),
    ],
    ids=["http-500", "invalid-json", "timeout", "connect-error"],
)
async def test_groq_failures_mark_the_client_span(
    telemetry: Capture,
    app: FastAPI,
    client: httpx2.AsyncClient,
    handler: Any,
    error_type: str,
    metric_status: str,
) -> None:
    _use(app, _groq(handler))
    project = await _project(client)

    await upload(client, project["id"])

    span = telemetry.span("groq.transcribe")
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes is not None and span.attributes["error.type"] == error_type
    assert telemetry.counts(TRANSCRIPTIONS) == {
        (("provider", "groq"), ("status", metric_status)): 1
    }


async def test_resource_identifies_service_version_environment_and_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("GIT_SHA", "abc1234")

    attributes = build_resource(Settings()).attributes

    assert attributes["service.name"] == "echonotes-api"
    assert attributes["deployment.environment"] == "dev"
    assert attributes["vcs.ref.head.revision"] == "abc1234"
    assert isinstance(attributes["service.version"], str)


# --- Logs ----------------------------------------------------------------------------------


async def test_json_logs_carry_the_trace_and_span_id_of_the_request(
    telemetry: Capture, client: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    project = await _project(client)
    capsys.readouterr()

    await upload(client, project["id"])

    records = parse_json_logs(capsys.readouterr().out)
    server = telemetry.span(f"POST {CREATE_ROUTE}")
    trace_id = format(server.context.trace_id, "032x")
    access = [r for r in records if r["logger"] == "app.access"]
    assert len(access) == 1
    assert access[0]["trace_id"] == trace_id
    assert access[0]["span_id"] == format(server.context.span_id, "016x")
    finished = [r for r in records if r["message"] == "transcription finished"]
    assert finished[0]["trace_id"] == trace_id
    assert finished[0]["span_id"] == format(
        telemetry.span("transcription.create").context.span_id, "016x"
    )
    assert all(len(r["trace_id"]) == 32 and len(r["span_id"]) == 16 for r in records)


async def test_json_logs_outside_a_request_have_null_trace_and_span_id(
    telemetry: Capture, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()

    logging.getLogger("app.test").info("background work")

    (record,) = parse_json_logs(capsys.readouterr().out)
    assert record["trace_id"] is None
    assert record["span_id"] is None
    assert record["request_id"] is None


async def test_logs_are_exported_over_otlp_with_trace_id_and_request_id(
    telemetry: Capture, client: httpx2.AsyncClient
) -> None:
    project = await _project(client)

    response = await upload(client, project["id"])

    server = telemetry.span(f"POST {CREATE_ROUTE}")
    exported = [
        r.log_record for r in telemetry.logs() if r.log_record.trace_id == server.context.trace_id
    ]
    bodies = {record.body for record in exported}
    assert {"transcription finished", "transcript created", "request completed"} <= bodies
    access = next(r for r in exported if r.body == "request completed")
    assert access.attributes is not None
    assert access.attributes["request_id"] == response.headers["x-request-id"]
    assert access.attributes["route"] == CREATE_ROUTE
    assert access.attributes["status"] == 201
    assert all(r.resource.attributes["service.name"] == "echonotes-api" for r in telemetry.logs())


async def test_otlp_exception_logs_keep_class_and_frames_but_not_the_message(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    _use(app, FailingTranscriber(Boom("SECRET-MESSAGE")))
    project = await _project(client)

    await upload(client, project["id"])

    errors = [r.log_record for r in telemetry.logs() if r.log_record.body == "unhandled exception"]
    assert len(errors) == 1
    attributes = errors[0].attributes
    assert attributes is not None
    assert attributes["exc_type"] == "Boom"
    assert "transcribe" in str(attributes["stack_trace"])
    assert "exception.message" not in attributes
    assert "SECRET-MESSAGE" not in telemetry.everything_as_text()


# --- Off by default ------------------------------------------------------------------------


def test_otlp_endpoints_are_derived_per_signal() -> None:
    assert otlp_endpoints("http://lgtm:4318/") == {
        "traces": "http://lgtm:4318/v1/traces",
        "metrics": "http://lgtm:4318/v1/metrics",
        "logs": "http://lgtm:4318/v1/logs",
    }


async def test_telemetry_is_off_without_an_endpoint(
    app: FastAPI, client: httpx2.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    project = await _project(client)
    capsys.readouterr()

    assert (await upload(client, project["id"])).status_code == 201

    assert app.state.telemetry is None
    assert instruments() is NOOP_INSTRUMENTS
    records = parse_json_logs(capsys.readouterr().out)
    assert records and all(r["trace_id"] is None and r["span_id"] is None for r in records)


def test_setup_is_a_no_op_with_a_blank_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "  ")

    assert Settings().telemetry_enabled is False


async def test_shutdown_restores_the_no_op_instruments(telemetry: Capture) -> None:
    assert telemetry.runtime is not None
    assert instruments() is not NOOP_INSTRUMENTS

    telemetry.runtime.shutdown()

    assert instruments() is NOOP_INSTRUMENTS


class _StubCollector(BaseHTTPRequestHandler):
    """Accepts OTLP/HTTP posts and records `(path, content type)`; never a real backend."""

    received: ClassVar[list[tuple[str, str]]] = []

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.received.append((self.path, self.headers.get("Content-Type", "")))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def collector() -> Iterator[str]:
    _StubCollector.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubCollector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


async def test_endpoint_setting_exports_all_signals_over_otlp_http_and_shuts_down_cleanly(
    monkeypatch: pytest.MonkeyPatch, collector: str
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", collector)
    monkeypatch.setenv("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    app = create_app()
    assert isinstance(app.state.telemetry, TelemetryRuntime)
    assert instruments() is not NOOP_INSTRUMENTS

    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/api/does-not-exist")).status_code == 404
    # Lifespan shutdown flushed and stopped everything; a second shutdown is harmless.
    app.state.telemetry.shutdown()

    paths = {path for path, _type in _StubCollector.received}
    assert paths == {"/v1/traces", "/v1/metrics", "/v1/logs"}
    assert {kind for _path, kind in _StubCollector.received} == {"application/x-protobuf"}
    assert instruments() is NOOP_INSTRUMENTS
    assert not any(isinstance(h, OtlpLogHandler) for h in logging.getLogger().handlers)
