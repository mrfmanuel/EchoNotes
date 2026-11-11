"""US-22 AC19, AC21: summarizer factory and the Gemini / Groq HTTP clients.

The HTTP layer is mocked with `httpx2.MockTransport` (the respx equivalent for httpx2): no test
ever reaches Gemini or Groq.
"""

import asyncio
import base64
import json
import logging
import time
from collections.abc import Callable

import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.summarization import (
    SummarizerConfigError,
    SummarizerError,
    SummarizerRateLimited,
    SummarizerTimeout,
    SummaryImage,
    SummaryRequest,
    build_summarizer,
)
from app.summarization.fake import FakeSummarizer
from app.summarization.gemini import GeminiSummarizer, effective_primary_timeout
from app.summarization.groq import GroqSummarizer

GEMINI_KEY = "AIza-LEAKED-GEMINI-KEY"
GROQ_KEY = "gsk_LEAKED-GROQ-KEY"
BASE = "https://gemini.example/v1beta"
REQUEST = SummaryRequest(
    system_instruction="SYSTEM-RULES",
    user_text="SECRET-USER-TEXT",
    images=[SummaryImage(1, "image/png", b"PNGBYTES")],
)
Handler = Callable[[httpx2.Request], httpx2.Response]


def gemini_ok(text: str = "<h1>Summary</h1>") -> httpx2.Response:
    return httpx2.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text[:5]}, {"text": text[5:]}]}}]}
    )


def gemini(handler: Handler, fallback: str = "flash-lite") -> tuple[GeminiSummarizer, list]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    summarizer = GeminiSummarizer(
        api_key=SecretStr(GEMINI_KEY),
        base_url=BASE,
        model="flash",
        fallback_model=fallback,
        timeout_seconds=5,
        transport=httpx2.MockTransport(record),
    )
    return summarizer, seen


def groq(handler: Handler) -> tuple[GroqSummarizer, list]:
    seen: list[httpx2.Request] = []

    def record(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    summarizer = GroqSummarizer(
        api_key=SecretStr(GROQ_KEY),
        base_url="https://groq.example/openai/v1",
        model="openai/gpt-oss-120b",
        timeout_seconds=5,
        transport=httpx2.MockTransport(record),
    )
    return summarizer, seen


# --- factory (AC21) ------------------------------------------------------------------------


def _settings(**values: str) -> Settings:
    return Settings(**values)  # type: ignore[arg-type]


def test_auto_provider_is_fake_without_a_gemini_key() -> None:
    assert isinstance(build_summarizer(_settings()), FakeSummarizer)


def test_auto_provider_is_gemini_when_the_gemini_key_is_set() -> None:
    summarizer = build_summarizer(_settings(gemini_api_key=GEMINI_KEY))

    assert isinstance(summarizer, GeminiSummarizer)


def test_explicit_fake_wins_over_a_gemini_key() -> None:
    summarizer = build_summarizer(_settings(summarizer_provider="fake", gemini_api_key="k"))

    assert isinstance(summarizer, FakeSummarizer)


def test_explicit_groq_uses_the_groq_key() -> None:
    summarizer = build_summarizer(_settings(summarizer_provider="groq", groq_api_key=GROQ_KEY))

    assert isinstance(summarizer, GroqSummarizer)


@pytest.mark.parametrize("provider", ["gemini", "groq"])
def test_explicit_provider_without_its_key_fails_at_startup(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUMMARIZER_PROVIDER", provider)

    with pytest.raises(SummarizerConfigError, match="API_KEY must be set"):
        create_app()


def test_empty_provider_env_means_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUMMARIZER_PROVIDER", "")

    assert create_app().state.summarizer.name == "fake"


def test_summary_settings_have_safe_defaults() -> None:
    settings = _settings()

    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.gemini_fallback_model == "gemini-3.5-flash-lite"
    assert settings.groq_summary_model == "openai/gpt-oss-120b"
    assert settings.summary_timeout_seconds == 90
    assert settings.summary_max_chars == 60000
    assert settings.summary_max_images == 8
    assert settings.summary_image_max_px == 1280


# --- Gemini --------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_gemini_sends_the_documented_request_with_inline_images() -> None:
    summarizer, seen = gemini(lambda _r: gemini_ok())

    result = await summarizer.summarize(REQUEST)

    assert result.fragment == "<h1>Summary</h1>" and result.model == "flash"
    request = seen[0]
    assert str(request.url) == f"{BASE}/models/flash:generateContent"
    assert request.headers["x-goog-api-key"] == GEMINI_KEY
    body = json.loads(request.content)
    assert body["system_instruction"] == {"parts": [{"text": "SYSTEM-RULES"}]}
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": "SECRET-USER-TEXT"}
    assert parts[2]["inline_data"] == {
        "mime_type": "image/png",
        "data": base64.b64encode(b"PNGBYTES").decode(),
    }
    assert body["generationConfig"] == {"maxOutputTokens": 8192}
    assert "temperature" not in json.dumps(body)


@pytest.mark.anyio
async def test_gemini_429_retries_once_with_the_fallback_model_and_records_it() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "/models/flash:" in str(request.url):
            return httpx2.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
        return gemini_ok("<p>from lite</p>")

    summarizer, seen = gemini(handler)

    result = await summarizer.summarize(REQUEST)

    assert result.model == "flash-lite"
    assert [r.url.path.rsplit("/", 1)[-1] for r in seen] == [
        "flash:generateContent",
        "flash-lite:generateContent",
    ]


@pytest.mark.anyio
async def test_gemini_429_on_both_models_raises_rate_limited() -> None:
    summarizer, seen = gemini(lambda _r: httpx2.Response(429))

    with pytest.raises(SummarizerRateLimited):
        await summarizer.summarize(REQUEST)
    assert len(seen) == 2


@pytest.mark.anyio
async def test_gemini_without_a_fallback_model_does_not_retry() -> None:
    summarizer, seen = gemini(lambda _r: httpx2.Response(429), fallback="")

    with pytest.raises(SummarizerRateLimited):
        await summarizer.summarize(REQUEST)
    assert len(seen) == 1


def _models(seen: list[httpx2.Request]) -> list[str]:
    return [r.url.path.rsplit("/", 1)[-1].removesuffix(":generateContent") for r in seen]


@pytest.mark.anyio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_gemini_429_500_503_fall_back_once_to_the_fallback_model(status: int) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "/models/flash:" in str(request.url):
            return httpx2.Response(status, json={"error": {"status": "UNAVAILABLE"}})
        return gemini_ok("<p>from lite</p>")

    summarizer, seen = gemini(handler)

    result = await summarizer.summarize(REQUEST)

    assert _models(seen) == ["flash", "flash-lite"]
    assert result.model == "flash-lite" and result.fragment == "<p>from lite</p>"


@pytest.mark.anyio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_gemini_failure_on_both_models_is_a_provider_error_after_one_fallback(
    status: int,
) -> None:
    summarizer, seen = gemini(lambda _r: httpx2.Response(status, text="SECRET-BODY"))

    with pytest.raises(SummarizerError) as info:
        await summarizer.summarize(REQUEST)
    assert _models(seen) == ["flash", "flash-lite"]
    assert info.value.status_code == status and "SECRET-BODY" not in str(info.value)


@pytest.mark.anyio
@pytest.mark.parametrize("status", [402, 400, 401, 403, 404])
async def test_gemini_402_and_other_4xx_fail_without_fallback(status: int) -> None:
    summarizer, seen = gemini(lambda _r: httpx2.Response(status, text="SECRET-BODY"))

    with pytest.raises(SummarizerError) as info:
        await summarizer.summarize(REQUEST)
    assert not isinstance(info.value, SummarizerRateLimited)
    assert info.value.status_code == status and _models(seen) == ["flash"]
    assert "SECRET-BODY" not in str(info.value)


def _primary_raises(error: type[httpx2.TransportError]) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "/models/flash:" in str(request.url):
            raise error("primary failed", request=request)
        return gemini_ok("<p>from lite</p>")

    return handler


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error", [httpx2.ReadTimeout, httpx2.ConnectTimeout, httpx2.ConnectError, httpx2.ReadError]
)
async def test_gemini_primary_timeout_or_transport_error_falls_back_once(
    error: type[httpx2.TransportError],
) -> None:
    summarizer, seen = gemini(_primary_raises(error))

    result = await summarizer.summarize(REQUEST)

    assert _models(seen) == ["flash", "flash-lite"]
    assert result.model == "flash-lite" and result.fragment == "<p>from lite</p>"


@pytest.mark.anyio
async def test_gemini_hanging_primary_is_cut_at_the_primary_timeout_and_falls_back() -> None:
    seen: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path.rsplit("/", 1)[-1])
        if "/models/flash:" in str(request.url):
            await asyncio.sleep(30)  # the model hangs; only GEMINI_PRIMARY_TIMEOUT_SECONDS stops it
        return gemini_ok("<p>from lite</p>")

    summarizer = GeminiSummarizer(
        api_key=SecretStr(GEMINI_KEY),
        base_url=BASE,
        model="flash",
        fallback_model="flash-lite",
        timeout_seconds=5,
        primary_timeout_seconds=0.1,
        transport=httpx2.MockTransport(handler),
    )
    began = time.monotonic()

    result = await summarizer.summarize(REQUEST)

    assert time.monotonic() - began < 3
    assert seen == ["flash:generateContent", "flash-lite:generateContent"]
    assert result.model == "flash-lite"


@pytest.mark.anyio
async def test_gemini_timeout_on_both_models_raises_summarizer_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    summarizer, seen = gemini(handler)

    with pytest.raises(SummarizerTimeout):
        await summarizer.summarize(REQUEST)
    assert _models(seen) == ["flash", "flash-lite"]


@pytest.mark.anyio
async def test_gemini_primary_timeout_then_fallback_http_error_is_a_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "/models/flash:" in str(request.url):
            raise httpx2.ReadTimeout("slow", request=request)
        return httpx2.Response(503)

    summarizer, seen = gemini(handler)

    with pytest.raises(SummarizerError) as info:
        await summarizer.summarize(REQUEST)
    assert info.value.status_code == 503 and _models(seen) == ["flash", "flash-lite"]


@pytest.mark.anyio
async def test_gemini_fallback_gets_only_the_remaining_budget() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        await asyncio.sleep(30)  # both models hang
        return gemini_ok()

    summarizer = GeminiSummarizer(
        api_key=SecretStr(GEMINI_KEY),
        base_url=BASE,
        model="flash",
        fallback_model="flash-lite",
        timeout_seconds=0.4,
        primary_timeout_seconds=0.2,
        transport=httpx2.MockTransport(handler),
    )
    began = time.monotonic()

    with pytest.raises(SummarizerTimeout):
        await summarizer.summarize(REQUEST)
    assert time.monotonic() - began < 2  # bounded by the whole budget, not 2 x primary


@pytest.mark.parametrize(
    ("primary", "total", "expected"), [(40, 90, 40), (90, 90, 45), (120, 90, 45), (5, 6, 5)]
)
def test_primary_timeout_is_clamped_below_the_summary_timeout(
    primary: float, total: float, expected: float
) -> None:
    assert effective_primary_timeout(primary, total) == expected


def test_primary_timeout_setting_defaults_to_40_and_reaches_the_summarizer() -> None:
    summarizer = build_summarizer(_settings(gemini_api_key=GEMINI_KEY))

    assert _settings().gemini_primary_timeout_seconds == 40
    assert isinstance(summarizer, GeminiSummarizer) and summarizer._primary_timeout == 40


def test_without_a_fallback_the_primary_model_gets_the_whole_budget() -> None:
    summarizer = build_summarizer(_settings(gemini_api_key=GEMINI_KEY, gemini_fallback_model=""))

    assert isinstance(summarizer, GeminiSummarizer) and summarizer._primary_timeout == 90


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, json={"candidates": []}),
        httpx2.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
        httpx2.Response(200, json={"candidates": [{"content": {"parts": [{"text": "  "}]}}]}),
        httpx2.Response(200, text="not json"),
    ],
)
async def test_gemini_empty_or_invalid_responses_are_provider_errors(
    response: httpx2.Response,
) -> None:
    summarizer, _ = gemini(lambda _r: response)

    with pytest.raises(SummarizerError):
        await summarizer.summarize(REQUEST)


@pytest.mark.anyio
async def test_gemini_connection_error_on_both_models_is_a_provider_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    summarizer, seen = gemini(handler)

    with pytest.raises(SummarizerError):
        await summarizer.summarize(REQUEST)
    assert _models(seen) == ["flash", "flash-lite"]


@pytest.mark.anyio
async def test_gemini_empty_primary_response_does_not_fall_back() -> None:
    summarizer, seen = gemini(lambda _r: httpx2.Response(200, json={"candidates": []}))

    with pytest.raises(SummarizerError):
        await summarizer.summarize(REQUEST)
    assert _models(seen) == ["flash"]


@pytest.mark.anyio
async def test_provider_logs_carry_no_key_prompt_or_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    summarizer, _ = gemini(lambda _r: httpx2.Response(500, text="SECRET-BODY"))
    caplog.set_level(logging.DEBUG)

    with pytest.raises(SummarizerError):
        await summarizer.summarize(REQUEST)

    logged = " ".join(f"{r.getMessage()} {vars(r)}" for r in caplog.records)
    assert "status_code" in logged
    for secret in (GEMINI_KEY, "SECRET-BODY", "SECRET-USER-TEXT", "SYSTEM-RULES"):
        assert secret not in logged


# --- Groq ----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_groq_sends_a_text_only_chat_completion() -> None:
    summarizer, seen = groq(
        lambda _r: httpx2.Response(200, json={"choices": [{"message": {"content": "<p>g</p>"}}]})
    )

    result = await summarizer.summarize(REQUEST)

    assert result.fragment == "<p>g</p>" and result.model == "openai/gpt-oss-120b"
    request = seen[0]
    assert str(request.url) == "https://groq.example/openai/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {GROQ_KEY}"
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["messages"] == [
        {"role": "system", "content": "SYSTEM-RULES"},
        {"role": "user", "content": "SECRET-USER-TEXT"},
    ]
    assert "UE5HQllURVM" not in request.content.decode()  # no base64 image bytes


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx2.Response(429), SummarizerRateLimited),
        (httpx2.Response(503), SummarizerError),
        (httpx2.Response(200, json={"choices": []}), SummarizerError),
    ],
)
async def test_groq_errors_are_mapped(response: httpx2.Response, error: type[Exception]) -> None:
    summarizer, _ = groq(lambda _r: response)

    with pytest.raises(error):
        await summarizer.summarize(REQUEST)


@pytest.mark.anyio
async def test_groq_timeout_raises_summarizer_timeout() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("slow", request=request)

    summarizer, _ = groq(handler)

    with pytest.raises(SummarizerTimeout):
        await summarizer.summarize(REQUEST)


# --- fake ----------------------------------------------------------------------------------


@pytest.mark.anyio
async def test_fake_summarizer_is_deterministic_and_places_every_image() -> None:
    request = SummaryRequest(
        "s",
        "u",
        [SummaryImage(1, "image/png", b""), SummaryImage(2, "image/png", b"")],
        transcript_titles=["A"],
        transcript_texts=["text"],
    )

    first = await FakeSummarizer().summarize(request)
    second = await FakeSummarizer().summarize(request)

    assert first == second and first.model == "fake-summarizer"
    assert '<figure data-screenshot="1">' in first.fragment
    assert '<figure data-screenshot="2">' in first.fragment
