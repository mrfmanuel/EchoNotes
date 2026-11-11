"""Helpers for the US-22 summary tests: stub summarizers, real images, awaiting jobs.

Never the real Gemini or Groq API: HTTP clients get an `httpx2.MockTransport`.
"""

import asyncio
import io
from dataclasses import dataclass, field
from typing import Any

import httpx2
from fastapi import FastAPI
from PIL import Image

from app.summarization import SummaryRequest, SummaryResult


def real_png(width: int = 64, height: int = 48, color: str = "red") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color).save(output, format="PNG")
    return output.getvalue()


def real_jpeg(width: int = 64, height: int = 48) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(output, format="JPEG")
    return output.getvalue()


async def wait_for_summary_jobs(app: FastAPI) -> None:
    """Deterministically await every background summary job started so far."""
    tasks: set[asyncio.Task[None]] = app.state.summary_tasks
    while tasks:
        await asyncio.gather(*list(tasks), return_exceptions=True)


@dataclass
class StubSummarizer:
    """Returns a fixed fragment (or raises `error`) and records the requests."""

    fragment: str = "<h1>Stub</h1><p>ok</p>"
    model: str = "stub-model"
    error: Exception | None = None
    name: str = "fake"
    requests: list[SummaryRequest] = field(default_factory=list)

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return SummaryResult(self.fragment, self.model)


@dataclass
class BlockingSummarizer:
    """Waits until `release` is set, so a job stays `running` for as long as a test needs."""

    name: str = "fake"
    release: asyncio.Event = field(default_factory=asyncio.Event)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    calls: int = 0

    async def summarize(self, request: SummaryRequest) -> SummaryResult:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return SummaryResult("<h1>Done</h1>", "blocking-model")


async def create_project(client: httpx2.AsyncClient, name: str = "Notes") -> dict[str, Any]:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def add_transcript(
    client: httpx2.AsyncClient, project_id: str, title: str = "Lecture", text: str | None = None
) -> dict[str, Any]:
    """Upload through the fake transcriber, then set the text if given."""
    created = await client.post(
        f"/api/projects/{project_id}/transcriptions",
        files={"file": ("lecture.mp3", b"ID3" + b"\x00" * 64, "audio/mpeg")},
        data={"title": title},
    )
    assert created.status_code == 201, created.text
    transcript: dict[str, Any] = created.json()
    if text is not None:
        edited = await client.patch(f"/api/transcriptions/{transcript['id']}", json={"text": text})
        assert edited.status_code == 200, edited.text
        transcript = edited.json()
    return transcript


async def add_screenshot(
    client: httpx2.AsyncClient,
    project_id: str,
    data: bytes,
    filename: str = "slide.png",
    transcript_id: str | None = None,
) -> dict[str, Any]:
    mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
    response = await client.post(
        f"/api/projects/{project_id}/screenshots",
        files={"file": (filename, data, mime)},
        data={"transcript_id": transcript_id} if transcript_id else None,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def generate(app: FastAPI, client: httpx2.AsyncClient, project_id: str) -> dict[str, Any]:
    """POST a summary, await the job and return `latest`."""
    started = await client.post(f"/api/projects/{project_id}/summaries")
    assert started.status_code == 202, started.text
    await wait_for_summary_jobs(app)
    latest = await client.get(f"/api/projects/{project_id}/summaries/latest")
    assert latest.status_code == 200, latest.text
    return latest.json()
