"""#12 POST /api/projects/{projectId}/transcriptions (US-05, US-06, US-07) on SQLite.

Uses the `fake` provider or stub transcribers injected through `get_transcriber`.
"""

import uuid
from datetime import datetime
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.config import get_settings
from app.db.models import Project, Transcript
from app.transcription import Transcriber, TranscriptionResult, get_transcriber
from tests.log_utils import parse_json_logs
from tests.project_utils import at, set_timestamps
from tests.transcription_utils import (
    AUDIO,
    RecordingTranscriber,
    provider_error,
    provider_timeout,
    upload,
)

pytestmark = pytest.mark.anyio

MIB = 1024 * 1024
TRANSCRIPT_KEYS = {
    "id",
    "project_id",
    "title",
    "slug",
    "text",
    "language",
    "duration_seconds",
    "provider",
    "source_filename",
    "created_at",
    "updated_at",
}


async def _project(client: httpx2.AsyncClient, name: str = "Lectures") -> dict[str, Any]:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def _use(app: FastAPI, transcriber: Transcriber) -> None:
    app.dependency_overrides[get_transcriber] = lambda: transcriber


async def _transcript_rows(session: AsyncSession) -> int:
    return (await session.execute(select(func.count(Transcript.id)))).scalar_one()


# --- 201 path (US-05 AC1, AC5) ---------------------------------------------------------------


async def test_upload_returns_201_transcript_from_fake_provider(
    client: httpx2.AsyncClient,
) -> None:
    project = await _project(client)

    response = await upload(client, project["id"], "Lecture 1.m4a", b"a" * 24_000)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == TRANSCRIPT_KEYS
    assert body["project_id"] == project["id"]
    assert body["title"] == "Lecture 1"
    assert body["slug"] == "lecture-1"
    assert body["text"] == "[fake transcript] Lecture 1.m4a (24000 bytes)"
    assert (body["language"], body["duration_seconds"]) == ("en", 1.5)
    assert body["provider"] == "fake"
    assert body["source_filename"] == "Lecture 1.m4a"
    assert datetime.fromisoformat(body["created_at"]).utcoffset() is not None


async def test_upload_of_audio_with_zero_duration_returns_201(
    client: httpx2.AsyncClient,
) -> None:
    # A 44-byte file (an empty WAV header) makes the fake provider report 0.0 s.
    project = await _project(client)

    response = await upload(client, project["id"], "empty.wav", b"R" * 44, "audio/wav")

    assert response.status_code == 201, response.text
    assert response.json()["duration_seconds"] == 0.0


async def test_created_transcript_is_persisted_and_listed_in_project_detail(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await _project(client)

    created = (await upload(client, project["id"])).json()

    row = await session.get(Transcript, uuid.UUID(created["id"]))
    assert row is not None and row.text == created["text"]
    detail = (await client.get(f"/api/projects/{project['id']}")).json()
    assert [t["id"] for t in detail["transcripts"]] == [created["id"]]
    assert detail["transcript_count"] == 1


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("a.mp3", "audio/mpeg"),
        ("a.WAV", "application/octet-stream"),
        ("a.m4a", "audio/x-m4a"),
        ("a.ogg", "audio/ogg"),
        ("a.webm", "video/webm"),
        ("blob", "audio/webm;codecs=opus"),
        ("recording", "audio/ogg; codecs=opus"),
    ],
)
async def test_supported_audio_types_are_accepted(
    client: httpx2.AsyncClient, filename: str, content_type: str
) -> None:
    project = await _project(client)

    response = await upload(client, project["id"], filename, AUDIO, content_type)

    assert response.status_code == 201, response.text


async def test_recording_without_extension_is_sent_to_provider_with_one(
    app: FastAPI, client: httpx2.AsyncClient
) -> None:
    stub = RecordingTranscriber()
    _use(app, stub)
    project = await _project(client)

    response = await upload(client, project["id"], "blob", AUDIO, "audio/webm;codecs=opus")

    assert response.status_code == 201
    assert stub.calls == [
        {
            "size": len(AUDIO),
            "filename": "blob.webm",
            "content_type": "audio/webm",
            "language": None,
        }
    ]
    assert (response.json()["title"], response.json()["source_filename"]) == ("blob", "blob")


async def test_file_exactly_at_the_limit_is_accepted(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_AUDIO_MB", "1")
    get_settings.cache_clear()
    project = await _project(client)

    response = await upload(client, project["id"], "a.mp3", b"a" * MIB)

    assert response.status_code == 201


# --- Rejections (US-05 AC2/AC3, US-07 AC3) ---------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("notes.txt", "text/plain"), ("photo.png", "image/png"), ("blob", "application/pdf")],
)
async def test_other_types_return_415_and_create_nothing(
    client: httpx2.AsyncClient, session: AsyncSession, filename: str, content_type: str
) -> None:
    project = await _project(client)

    response = await upload(client, project["id"], filename, AUDIO, content_type)

    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_media_type"
    assert await _transcript_rows(session) == 0


async def test_file_over_25_mib_returns_413_audio_too_large(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await _project(client)

    response = await upload(client, project["id"], "big.wav", b"\x00" * (25 * MIB + 1))

    assert response.status_code == 413
    assert response.json() == {
        "detail": "Audio file is larger than 25 MB.",
        "code": "audio_too_large",
    }
    assert await _transcript_rows(session) == 0


async def test_max_audio_mb_setting_controls_the_limit(
    client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_AUDIO_MB", "1")
    get_settings.cache_clear()
    project = await _project(client)

    response = await upload(client, project["id"], "a.mp3", b"a" * (MIB + 1))

    assert response.status_code == 413


async def test_empty_file_returns_422(client: httpx2.AsyncClient, session: AsyncSession) -> None:
    project = await _project(client)

    response = await upload(client, project["id"], "empty.mp3", b"")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert await _transcript_rows(session) == 0


@pytest.mark.parametrize("language", ["fr", "EN", "english", "es-ES"])
async def test_invalid_language_returns_422(client: httpx2.AsyncClient, language: str) -> None:
    project = await _project(client)

    response = await upload(client, project["id"], language=language)

    assert response.status_code == 422


async def test_missing_file_returns_422(client: httpx2.AsyncClient) -> None:
    project = await _project(client)

    response = await client.post(
        f"/api/projects/{project['id']}/transcriptions", data={"language": "en"}
    )

    assert response.status_code == 422


async def test_unknown_project_returns_404_not_found(client: httpx2.AsyncClient) -> None:
    response = await upload(client, uuid.uuid4())

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found", "code": "not_found"}


# --- Language hint (US-07) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("form", "sent"),
    [
        pytest.param({}, None, id="omitted"),
        pytest.param({"language": ""}, None, id="empty-field-is-omitted"),
        pytest.param({"language": "auto"}, None, id="auto"),
        pytest.param({"language": "en"}, "en", id="en"),
        pytest.param({"language": "es"}, "es", id="es"),
        pytest.param({"language": "pt"}, "pt", id="pt"),
    ],
)
async def test_language_auto_sends_none_and_codes_pass_through(
    app: FastAPI, client: httpx2.AsyncClient, form: dict[str, str], sent: str | None
) -> None:
    stub = RecordingTranscriber()
    _use(app, stub)
    project = await _project(client)

    response = await upload(client, project["id"], **form)

    assert response.status_code == 201
    assert stub.calls[0]["language"] == sent


@pytest.mark.parametrize(
    ("returned", "hint", "stored"),
    [("pt", "es", "pt"), (None, "es", "es"), (None, "auto", None)],
)
async def test_stored_language_is_provider_then_hint_then_null(
    app: FastAPI, client: httpx2.AsyncClient, returned: str | None, hint: str, stored: str | None
) -> None:
    _use(app, RecordingTranscriber(result=TranscriptionResult("t", returned, None)))
    project = await _project(client)

    response = await upload(client, project["id"], language=hint)

    assert (response.json()["language"], response.json()["duration_seconds"]) == (stored, None)


# --- Title and slug --------------------------------------------------------------------------


async def test_title_form_field_is_trimmed_and_slugged(client: httpx2.AsyncClient) -> None:
    project = await _project(client)

    body = (await upload(client, project["id"], title="  Física: Clase 2  ")).json()

    assert (body["title"], body["slug"]) == ("Física: Clase 2", "fisica-clase-2")


async def test_blank_title_defaults_to_filename_without_extension(
    client: httpx2.AsyncClient,
) -> None:
    project = await _project(client)

    body = (await upload(client, project["id"], "Weekly sync.ogg", title="   ")).json()

    assert body["title"] == "Weekly sync"


async def test_title_over_200_chars_returns_422(client: httpx2.AsyncClient) -> None:
    project = await _project(client)

    assert (await upload(client, project["id"], title="x" * 201)).status_code == 422
    assert (await upload(client, project["id"], title="x" * 200)).status_code == 201


async def test_slug_falls_back_to_transcript_and_is_not_unique(
    client: httpx2.AsyncClient,
) -> None:
    project = await _project(client)

    first = (await upload(client, project["id"], title="¿¿??")).json()
    second = (await upload(client, project["id"], title="!!")).json()

    assert (first["slug"], second["slug"]) == ("transcript", "transcript")


# --- Project updated_at (US-02 AC3) ----------------------------------------------------------


async def test_creating_a_transcript_bumps_project_updated_at(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    older = await _project(client, "Older")
    newer = await _project(client, "Newer")
    await set_timestamps(session, older["id"], created_at=at(1), updated_at=at(1))
    await set_timestamps(session, newer["id"], created_at=at(2), updated_at=at(2))

    await upload(client, older["id"])

    listed = (await client.get("/api/projects")).json()
    assert [p["name"] for p in listed] == ["Older", "Newer"]
    assert datetime.fromisoformat(listed[0]["updated_at"]) > at(2)


# --- Provider failures (US-05 AC4) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("transcriber", "status_code", "code"),
    [(provider_error(), 502, "provider_error"), (provider_timeout(), 504, "provider_timeout")],
    ids=["error", "timeout"],
)
async def test_provider_failure_maps_to_502_or_504_and_creates_no_row(
    app: FastAPI,
    client: httpx2.AsyncClient,
    session: AsyncSession,
    transcriber: Transcriber,
    status_code: int,
    code: str,
) -> None:
    _use(app, transcriber)
    project = await _project(client)
    await set_timestamps(session, project["id"], created_at=at(1), updated_at=at(1))

    response = await upload(client, project["id"])

    assert response.status_code == status_code
    assert response.json()["code"] == code
    assert "try again" in response.json()["detail"]
    assert await _transcript_rows(session) == 0
    session.expire_all()
    stored = await session.get(Project, uuid.UUID(project["id"]))
    assert stored is not None and stored.updated_at == at(1)


# --- Privacy (US-05 AC6, NFR-Privacy) --------------------------------------------------------


@pytest.mark.parametrize("failing", [False, True], ids=["success", "provider-error"])
async def test_upload_is_always_closed_after_the_request(
    app: FastAPI, client: httpx2.AsyncClient, monkeypatch: pytest.MonkeyPatch, failing: bool
) -> None:
    closed: list[str | None] = []
    original_close = UploadFile.close

    async def tracking_close(self: UploadFile) -> None:
        closed.append(self.filename)
        await original_close(self)

    monkeypatch.setattr(UploadFile, "close", tracking_close)
    if failing:
        _use(app, provider_error())
    project = await _project(client)

    await upload(client, project["id"], "a.mp3")

    assert "a.mp3" in closed


async def test_raw_audio_is_not_stored_in_the_database(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    project = await _project(client)
    marker = b"RAW-AUDIO-MARKER" * 100

    created = (await upload(client, project["id"], "a.mp3", marker)).json()

    row = await session.get(Transcript, uuid.UUID(created["id"]))
    assert row is not None
    stored = " ".join(str(getattr(row, c.key)) for c in Transcript.__table__.columns)
    assert "RAW-AUDIO-MARKER" not in stored


@pytest.mark.parametrize("failing", [False, True], ids=["success", "provider-error"])
async def test_logs_contain_no_transcript_text_title_or_filename(
    app: FastAPI,
    client: httpx2.AsyncClient,
    capsys: pytest.CaptureFixture[str],
    failing: bool,
) -> None:
    stub = RecordingTranscriber(result=TranscriptionResult("SECRET-TEXT words", "en", 2.0))
    _use(app, provider_error() if failing else stub)
    project = await _project(client)
    capsys.readouterr()

    response = await upload(
        client, project["id"], "SECRET-FILENAME.m4a", title="SECRET-TITLE notes"
    )

    output = capsys.readouterr().out
    records = parse_json_logs(output)
    assert response.status_code == (502 if failing else 201)
    assert any(r["logger"].startswith("app.services.transcriptions") for r in records)
    assert any(r.get("size_bytes") == len(AUDIO) for r in records)
    for secret in ("SECRET-TEXT", "SECRET-TITLE", "SECRET-FILENAME"):
        assert secret not in output
