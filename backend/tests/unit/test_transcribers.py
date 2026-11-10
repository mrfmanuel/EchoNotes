"""#11 Transcriber interface: fake provider, Groq provider (mocked HTTP) and the factory.

The Groq tests use `httpx2.MockTransport`; no test ever reaches the network.
"""

import logging
from collections.abc import Callable

import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.main import create_app
from app.transcription import (
    ProviderError,
    ProviderTimeout,
    Transcriber,
    TranscriberConfigError,
    TranscriptionResult,
    build_transcriber,
)
from app.transcription.fake import FakeTranscriber
from app.transcription.groq import GroqTranscriber, normalize_language

pytestmark = pytest.mark.anyio

API_KEY = "gsk_test_key_never_real"
BASE_URL = "https://groq.test/openai/v1"
AUDIO = b"RIFF" + b"\x01" * 1000
Handler = Callable[[httpx2.Request], httpx2.Response]


def _groq(handler: Handler, timeout: float = 120, model: str = "whisper-large-v3-turbo"):
    return GroqTranscriber(
        api_key=SecretStr(API_KEY),
        base_url=BASE_URL,
        model=model,
        timeout_seconds=timeout,
        transport=httpx2.MockTransport(handler),
    )


def _ok(json: object) -> Handler:
    return lambda _request: httpx2.Response(200, json=json)


def _form_field(name: str, value: str) -> bytes:
    return f'name="{name}"\r\n\r\n{value}\r\n'.encode()


# --- Interface -------------------------------------------------------------------------------


def test_transcription_result_is_frozen_dataclass() -> None:
    result = TranscriptionResult("hi", "en", 1.0)

    with pytest.raises(AttributeError):
        result.text = "changed"  # type: ignore[misc]


def test_both_providers_satisfy_the_transcriber_protocol() -> None:
    providers: list[Transcriber] = [FakeTranscriber(), _groq(_ok({"text": ""}))]

    assert [p.name for p in providers] == ["fake", "groq"]


# --- Fake provider ---------------------------------------------------------------------------


async def test_fake_returns_exact_text_language_hint_and_duration() -> None:
    result = await FakeTranscriber().transcribe(b"x" * 24_000, "lecture.m4a", "audio/mp4", "es")

    assert result == TranscriptionResult("[fake transcript] lecture.m4a (24000 bytes)", "es", 1.5)


async def test_fake_defaults_language_to_en_when_hint_is_none() -> None:
    result = await FakeTranscriber().transcribe(b"x" * 12_345, "a.mp3", "audio/mpeg", None)

    assert result.language == "en"
    assert result.duration_seconds == round(12_345 / 16000, 2)


async def test_fake_is_deterministic() -> None:
    fake = FakeTranscriber()

    first = await fake.transcribe(AUDIO, "a.wav", "audio/wav", None)
    second = await fake.transcribe(AUDIO, "a.wav", "audio/wav", None)

    assert first == second
    assert fake.name == "fake"


# --- Groq provider: request ------------------------------------------------------------------


async def test_groq_posts_multipart_with_auth_model_and_language() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, json={"text": "hola", "language": "spanish", "duration": 3.2})

    await _groq(handler, timeout=7.5, model="whisper-test").transcribe(
        AUDIO, "clase.wav", "audio/wav", "es"
    )

    request = captured[0]
    body = request.read()
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/audio/transcriptions"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="file"; filename="clase.wav"\r\nContent-Type: audio/wav' in body
    assert AUDIO in body
    for name, value in [
        ("model", "whisper-test"),
        ("response_format", "verbose_json"),
        ("temperature", "0"),
        ("language", "es"),
    ]:
        assert _form_field(name, value) in body
    assert request.extensions["timeout"]["read"] == 7.5


async def test_groq_omits_language_when_hint_is_none() -> None:
    captured: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, json={"text": "hello"})

    await _groq(handler).transcribe(AUDIO, "a.mp3", "audio/mpeg", None)

    body = captured[0].read()
    assert b'name="language"' not in body
    assert _form_field("model", "whisper-large-v3-turbo") in body


# --- Groq provider: response mapping ---------------------------------------------------------


async def test_groq_maps_text_duration_and_normalizes_language_name() -> None:
    handler = _ok({"text": "Hola", "language": "Spanish", "duration": 12})

    result = await _groq(handler).transcribe(AUDIO, "a.ogg", "audio/ogg", None)

    assert result == TranscriptionResult("Hola", "es", 12.0)


async def test_groq_missing_duration_and_language_fall_back_to_none_and_hint() -> None:
    result = await _groq(_ok({"text": "Olá"})).transcribe(AUDIO, "a.ogg", "audio/ogg", "pt")

    assert result == TranscriptionResult("Olá", "pt", None)


@pytest.mark.parametrize(
    ("value", "hint", "expected"),
    [
        ("english", None, "en"),
        ("spanish", None, "es"),
        ("Portuguese", None, "pt"),
        ("EN", None, "en"),
        ("fr", "es", "fr"),
        (None, "es", "es"),
        (None, None, None),
        ("klingon", "en", "en"),
        (42, None, None),
    ],
)
def test_normalize_language_to_iso_639_1(
    value: object, hint: str | None, expected: str | None
) -> None:
    assert normalize_language(value, hint) == expected


# --- Groq provider: errors -------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [400, 401, 413, 429, 500, 503])
async def test_groq_non_2xx_raises_provider_error_with_status_only(status_code: int) -> None:
    handler: Handler = lambda _r: httpx2.Response(status_code, text="secret response text")  # noqa: E731

    with pytest.raises(ProviderError) as info:
        await _groq(handler).transcribe(AUDIO, "private.wav", "audio/wav", None)

    assert info.value.status_code == status_code
    assert str(info.value) == f"groq transcription failed (status {status_code})"


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, text="not json"),
        httpx2.Response(200, json=["a list"]),
        httpx2.Response(200, json={"no_text": True}),
    ],
    ids=["invalid-json", "not-an-object", "missing-text"],
)
async def test_groq_malformed_response_raises_provider_error(response: httpx2.Response) -> None:
    with pytest.raises(ProviderError):
        await _groq(lambda _r: response).transcribe(AUDIO, "a.wav", "audio/wav", None)


async def test_groq_connection_error_raises_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderError) as info:
        await _groq(handler).transcribe(AUDIO, "a.wav", "audio/wav", None)

    assert info.value.status_code is None
    assert info.value.__cause__ is None


@pytest.mark.parametrize("error", [httpx2.ReadTimeout, httpx2.ConnectTimeout, httpx2.WriteTimeout])
async def test_groq_timeout_raises_provider_timeout(error: type[httpx2.TimeoutException]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error("timed out", request=request)

    with pytest.raises(ProviderTimeout) as info:
        await _groq(handler).transcribe(AUDIO, "a.wav", "audio/wav", None)

    assert str(info.value) == "groq transcription timed out"


async def test_groq_error_logs_contain_no_key_filename_or_response_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler: Handler = lambda _r: httpx2.Response(500, text="secret response text")  # noqa: E731
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ProviderError):
        await _groq(handler).transcribe(AUDIO, "private-name.wav", "audio/wav", None)

    logged = " ".join(f"{r.getMessage()} {vars(r)}" for r in caplog.records)
    assert "status_code" in logged
    for secret in (API_KEY, "private-name", "secret response text"):
        assert secret not in logged


# --- Factory and dependency ------------------------------------------------------------------


def test_factory_returns_fake_by_default() -> None:
    assert isinstance(build_transcriber(Settings()), FakeTranscriber)


def test_factory_returns_groq_configured_from_settings() -> None:
    settings = Settings(
        transcriber_provider="groq",
        groq_api_key=SecretStr(API_KEY),
        groq_base_url=BASE_URL + "/",
        groq_model="whisper-x",
        transcribe_timeout_seconds=9,
    )

    transcriber = build_transcriber(settings)

    assert isinstance(transcriber, GroqTranscriber)
    assert transcriber.name == "groq"
    assert (transcriber._url, transcriber._model, transcriber._timeout) == (
        f"{BASE_URL}/audio/transcriptions",
        "whisper-x",
        9,
    )


@pytest.mark.parametrize("key", ["", "   "])
def test_groq_without_api_key_fails_fast_at_startup_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.setenv("TRANSCRIBER_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", key)
    get_settings.cache_clear()

    with pytest.raises(TranscriberConfigError, match="GROQ_API_KEY must be set"):
        create_app()


def test_app_exposes_the_configured_transcriber(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRANSCRIBER_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", API_KEY)
    get_settings.cache_clear()

    app = create_app()

    assert app.state.transcriber.name == "groq"
    assert API_KEY not in repr(app.state.transcriber._api_key)
