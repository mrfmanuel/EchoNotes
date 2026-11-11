"""#29 privacy: no customer data or credentials in any telemetry signal (NFR-Privacy).

Runs the whole journey (create project, upload + transcribe through the Groq client against a
mock transport, edit, screenshot, download, export) plus provider and unhandled failures, all
with distinctive secrets, then asserts that none of them appears in any exported span (name,
attributes, events, status), metric (names and labels), OTLP log record, or stdout JSON line.
"""

import re
import sqlite3
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from opentelemetry.trace import StatusCode
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import get_settings
from app.transcription import ProviderError, get_transcriber
from app.transcription.groq import GroqTranscriber
from tests.image_utils import PNG
from tests.image_utils import upload as upload_image
from tests.telemetry_utils import Capture
from tests.transcription_utils import FailingTranscriber, upload

pytestmark = pytest.mark.anyio

API_KEY = "gsk_LEAKED-API-KEY-0123456789"
DB_PASSWORD = "LEAKED-DB-PASSWORD"
DB_USER = "leaked_db_user"
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@leaked-db-host.example:5432/leaked_db"
PROJECT_NAME = "SECRET-PROJECT-NAME Física"
TITLE = "SECRET-TITLE weekly notes"
FILENAME = "SECRET-FILENAME-lecture.m4a"
SCREENSHOT_NAME = "SECRET-SCREENSHOT-NAME.png"
TEXT = "SECRET-TRANSCRIPT-TEXT the quarterly numbers"
EDITED_TEXT = "SECRET-EDITED-TEXT corrected"
PROVIDER_BODY = "SECRET-PROVIDER-ERROR-BODY"
EXCEPTION_MESSAGE = "SECRET-EXCEPTION-MESSAGE with SECRET-TITLE"
AUDIO_MARKER = b"SECRET-AUDIO-BYTES"
AUDIO = b"ID3" + AUDIO_MARKER * 2000
IMAGE_MARKER = b"SECRET-IMAGE-BYTES"

SECRETS = (
    API_KEY,
    DB_PASSWORD,
    DB_USER,
    DATABASE_URL,
    "SECRET-PROJECT-NAME",
    "SECRET-TITLE",
    "SECRET-FILENAME",
    "SECRET-SCREENSHOT-NAME",
    "SECRET-TRANSCRIPT-TEXT",
    "SECRET-EDITED-TEXT",
    PROVIDER_BODY,
    "SECRET-EXCEPTION-MESSAGE",
    AUDIO_MARKER.decode(),
    IMAGE_MARKER.decode(),
)
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@pytest.fixture(autouse=True)
def secret_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", API_KEY)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    get_settings.cache_clear()


def _groq(app: FastAPI, responder: Any) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return responder(request)

    transcriber = GroqTranscriber(
        api_key=get_settings().groq_api_key,
        base_url="https://api.groq.example/openai/v1",
        model="whisper-large-v3-turbo",
        timeout_seconds=5,
        transport=httpx2.MockTransport(handler),
    )
    app.dependency_overrides[get_transcriber] = lambda: transcriber
    return seen


def _assert_no_secrets(text: str) -> None:
    """Case-insensitive, so slugs (`secret-title-weekly-notes`) count as leaks too."""
    lowered = text.lower()
    leaked = [secret for secret in SECRETS if secret.lower() in lowered]
    assert leaked == []


async def _journey(app: FastAPI, client: httpx2.AsyncClient) -> None:
    seen = _groq(
        app,
        lambda _r: httpx2.Response(200, json={"text": TEXT, "language": "es", "duration": 2.0}),
    )
    project = (await client.post("/api/projects", json={"name": PROJECT_NAME})).json()
    created = await upload(client, project["id"], FILENAME, AUDIO, title=TITLE, language="es")
    assert created.status_code == 201, created.text
    assert seen and seen[0].headers["authorization"] == f"Bearer {API_KEY}"  # the key was used
    transcript_id = created.json()["id"]
    edited = await client.patch(f"/api/transcriptions/{transcript_id}", json={"text": EDITED_TEXT})
    assert edited.status_code == 200
    image = await upload_image(client, project["id"], PNG + IMAGE_MARKER, SCREENSHOT_NAME)
    assert image.status_code == 201, image.text
    download = await client.get(f"/api/transcriptions/{transcript_id}/download?format=md")
    assert download.status_code == 200
    exported = await client.get(f"/api/projects/{project['id']}/export")
    assert exported.status_code == 200 and IMAGE_MARKER in exported.content

    # Failures: provider error with a body, then an unhandled bug whose message echoes input.
    _groq(app, lambda _r: httpx2.Response(500, text=PROVIDER_BODY))
    failed = await upload(client, project["id"], FILENAME, AUDIO, title=TITLE)
    assert failed.status_code == 502
    app.dependency_overrides[get_transcriber] = lambda: FailingTranscriber(
        RuntimeError(EXCEPTION_MESSAGE)
    )
    crashed = await upload(client, project["id"], FILENAME, AUDIO, title=TITLE)
    assert crashed.status_code == 500


async def test_telemetry_contains_no_customer_data(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    await _journey(app, client)

    exported = telemetry.everything_as_text()
    names = {span.name for span in telemetry.spans()}
    assert {"transcription.create", "groq.transcribe", "export.build"} <= names
    assert telemetry.logs() and "echonotes.transcriptions" in telemetry.metric_names()
    _assert_no_secrets(exported)


async def test_no_secret_in_stdout_json_logs_with_telemetry_on(
    telemetry: Capture,
    app: FastAPI,
    client: httpx2.AsyncClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capsys.readouterr()

    await _journey(app, client)

    output = capsys.readouterr().out
    assert '"trace_id"' in output and '"exc_type": "RuntimeError"' in output
    _assert_no_secrets(output)


async def test_exception_details_never_reach_span_events_or_status(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    await _journey(app, client)

    for span in telemetry.spans():
        assert span.status.description is None, span.name
        for span_event in span.events:
            allowed = {"exception.type"}
            assert set(span_event.attributes or {}) <= allowed, (span.name, span_event.name)


async def test_metric_labels_are_low_cardinality_and_never_ids(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    await _journey(app, client)

    for rm in telemetry.metrics().resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                for point in metric.data.data_points:
                    for key, value in (point.attributes or {}).items():
                        assert not UUID.search(str(value)), (metric.name, key, value)
    labels = {key for attrs, _ in telemetry.points("echonotes.transcriptions") for key in attrs}
    assert labels == {"provider", "status"}
    assert {key for attrs, _ in telemetry.points("echonotes.exports") for key in attrs} == {
        "status"
    }


async def test_provider_error_message_is_not_attached_anywhere(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    # A transcriber whose exception text echoes user input (status code only in telemetry).
    app.dependency_overrides[get_transcriber] = lambda: FailingTranscriber(
        ProviderError(f"stub {TITLE}", 503)
    )
    project = (await client.post("/api/projects", json={"name": PROJECT_NAME})).json()

    response = await upload(client, project["id"], FILENAME, AUDIO, title=TITLE)

    assert response.status_code == 502
    _assert_no_secrets(telemetry.everything_as_text())


def _fail_like_postgres(
    _conn: object, _cursor: object, statement: str, parameters: Any, *_args: object
) -> None:
    """Postgres puts the row values in the driver error (`DETAIL: Failing row contains`)."""
    if statement.startswith("INSERT INTO transcript "):
        raise sqlite3.IntegrityError(
            'null value in column "slug" violates not-null constraint\n'
            f"DETAIL:  Failing row contains {tuple(parameters)}."
        )


async def test_database_error_parameters_never_reach_telemetry(
    telemetry: Capture,
    engine: AsyncEngine,
    app: FastAPI,
    client: httpx2.AsyncClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A failing INSERT: the driver error text holds the title, text and filename, which the SQL
    # span puts in its status description and SQLAlchemy in the exception message.
    event.listen(engine.sync_engine, "before_cursor_execute", _fail_like_postgres)
    _groq(app, lambda _r: httpx2.Response(200, json={"text": TEXT}))
    project = (await client.post("/api/projects", json={"name": PROJECT_NAME})).json()

    response = await upload(client, project["id"], FILENAME, AUDIO, title=TITLE)

    assert response.status_code == 500
    failed_sql = [
        s
        for s in telemetry.spans()
        if s.attributes and "INSERT INTO transcript " in str(s.attributes.get("db.statement"))
    ]
    assert failed_sql and failed_sql[0].status.status_code is StatusCode.ERROR
    assert telemetry.counts("echonotes.transcriptions") == {
        (("provider", "groq"), ("status", "server_error")): 1
    }
    _assert_no_secrets(telemetry.everything_as_text())
    _assert_no_secrets(capsys.readouterr().out)
