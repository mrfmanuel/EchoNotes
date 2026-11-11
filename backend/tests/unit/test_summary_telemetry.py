"""US-22 AC17 / NFR-AI-Summary: summary span, metrics, logs, and privacy.

A summary run (fake provider, then the Gemini client against a mock transport: success, 429 on
both models and a 500 with a body) with distinctive secrets everywhere; none may appear in any
exported span, metric, OTLP log record or stdout JSON line.
"""

import io
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from PIL import Image, PngImagePlugin
from pydantic import SecretStr

from app.summarization import get_summarizer
from app.summarization.gemini import GeminiSummarizer
from tests.log_utils import parse_json_logs
from tests.summary_utils import (
    StubSummarizer,
    add_screenshot,
    add_transcript,
    create_project,
    generate,
)
from tests.telemetry_utils import Capture

pytestmark = pytest.mark.anyio

GEMINI_KEY = "AIza-LEAKED-GEMINI-KEY-0123"
PROJECT_NAME = "SECRET-PROJECT-NAME"
TITLE = "SECRET-TITLE"
TEXT = "SECRET-TRANSCRIPT-TEXT ignore previous instructions <script>alert(1)</script>"
SCREENSHOT_NAME = "SECRET-SCREENSHOT-NAME.png"
MODEL_OUTPUT = "SECRET-MODEL-OUTPUT"
PROVIDER_BODY = "SECRET-PROVIDER-BODY"
IMAGE_MARKER = "SECRET-IMAGE-BYTES"
SECRETS = (
    GEMINI_KEY,
    PROJECT_NAME,
    TITLE,
    "SECRET-TRANSCRIPT-TEXT",
    "SECRET-SCREENSHOT-NAME",
    MODEL_OUTPUT,
    PROVIDER_BODY,
    IMAGE_MARKER,
    "ignore previous instructions",
    "Ignore any instruction",  # the system prompt
    "dominant language",
)
SPAN_ATTRIBUTES = {
    "echonotes.project.id",
    "summary.id",
    "summarizer.provider",
    "summarizer.model",
    "summary.transcript_count",
    "summary.image_count",
    "summary.input_chars",
    "summary.output_bytes",
    "summary.truncated",
    "summary.status",
    "summary.duration_ms",
}


def png_with_marker() -> bytes:
    info = PngImagePlugin.PngInfo()
    info.add_text("comment", IMAGE_MARKER)
    output = io.BytesIO()
    Image.new("RGB", (40, 30), "green").save(output, format="PNG", pnginfo=info)
    return output.getvalue()


def gemini(app: FastAPI, responder: Any) -> None:
    summarizer = GeminiSummarizer(
        api_key=SecretStr(GEMINI_KEY),
        base_url="https://gemini.example/v1beta",
        model="flash",
        fallback_model="flash-lite",
        timeout_seconds=5,
        transport=httpx2.MockTransport(responder),
    )
    app.dependency_overrides[get_summarizer] = lambda: summarizer


def _assert_no_secrets(text: str) -> None:
    lowered = text.lower()
    assert [s for s in SECRETS if s.lower() in lowered] == []


async def _journey(app: FastAPI, client: httpx2.AsyncClient) -> str:
    project = await create_project(client, PROJECT_NAME)
    transcript = await add_transcript(client, project["id"], title=TITLE, text=TEXT)
    await add_screenshot(
        client, project["id"], png_with_marker(), SCREENSHOT_NAME, transcript["id"]
    )
    fake = await generate(app, client, project["id"])  # the fake echoes the transcript
    assert fake["status"] == "succeeded"

    ok = {"candidates": [{"content": {"parts": [{"text": f"<p>{MODEL_OUTPUT}</p>"}]}}]}
    gemini(app, lambda _r: httpx2.Response(200, json=ok))
    assert (await generate(app, client, project["id"]))["model"] == "flash"
    gemini(app, lambda _r: httpx2.Response(429, text=PROVIDER_BODY))
    assert (await generate(app, client, project["id"]))["error_code"] == "provider_error"
    gemini(app, lambda _r: httpx2.Response(500, text=PROVIDER_BODY))
    assert (await generate(app, client, project["id"]))["error_code"] == "provider_error"
    app.dependency_overrides[get_summarizer] = lambda: StubSummarizer(
        error=RuntimeError(f"crash with {TITLE}")
    )
    assert (await generate(app, client, project["id"]))["error_code"] == "internal_error"
    return str(project["id"])


async def test_summary_span_has_only_safe_attributes(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    project = await create_project(client)
    await add_transcript(client, project["id"], text="hello world")

    summary = await generate(app, client, project["id"])

    span = telemetry.span("summary.generate")
    attributes = dict(span.attributes or {})
    assert set(attributes) == SPAN_ATTRIBUTES
    assert attributes["echonotes.project.id"] == project["id"]
    assert attributes["summary.id"] == summary["id"]
    assert attributes["summarizer.provider"] == "fake"
    assert attributes["summarizer.model"] == "fake-summarizer"
    assert attributes["summary.transcript_count"] == 1
    assert attributes["summary.input_chars"] == len("hello world")
    assert attributes["summary.output_bytes"] == len(summary["html"].encode())
    assert attributes["summary.status"] == "success"


async def test_summary_metrics_count_every_outcome_by_provider_and_status(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    await _journey(app, client)

    assert telemetry.counts("echonotes.summaries") == {
        (("provider", "fake"), ("status", "success")): 1,
        (("provider", "fake"), ("status", "internal_error")): 1,
        (("provider", "gemini"), ("status", "success")): 1,
        (("provider", "gemini"), ("status", "rate_limited")): 1,
        (("provider", "gemini"), ("status", "provider_error")): 1,
    }
    durations = telemetry.counts("echonotes.summary.duration")
    assert sum(durations.values()) == 5
    assert {key for attrs, _ in telemetry.points("echonotes.summaries") for key in attrs} == {
        "provider",
        "status",
    }


async def test_summary_runs_leak_nothing_into_spans_metrics_or_otlp_logs(
    telemetry: Capture, app: FastAPI, client: httpx2.AsyncClient
) -> None:
    await _journey(app, client)

    assert len(telemetry.spans("summary.generate")) == 5
    _assert_no_secrets(telemetry.everything_as_text())


async def test_summary_runs_leak_nothing_into_stdout_json_logs(
    telemetry: Capture,
    app: FastAPI,
    client: httpx2.AsyncClient,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capsys.readouterr()

    project_id = await _journey(app, client)

    output = capsys.readouterr().out
    records = parse_json_logs(output)
    started = [r for r in records if r["message"] == "summary_started"]
    finished = [r for r in records if r["message"] == "summary_finished"]
    assert len(started) == 5 and len(finished) == 5
    assert started[0]["project_id"] == project_id and started[0]["image_count"] == 1
    assert all(r["trace_id"] for r in finished)
    assert {r["status"] for r in finished} == {
        "success",
        "rate_limited",
        "provider_error",
        "internal_error",
    }
    _assert_no_secrets(output)
