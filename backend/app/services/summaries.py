"""AI project summaries (US-22): start/read/download, the background job and startup recovery.

The job runs as an `asyncio` task (strong references in `app.state.summary_tasks`, cancelled at
shutdown) with its own short-lived sessions: load + mark `running`, call the provider (no DB
connection held), then store the result. Privacy (AC17): only IDs, counts, sizes, durations,
provider, model and status are logged or traced; never the prompt, transcripts, titles,
filenames, images or any provider response text.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.base import utcnow
from app.db.models import Project, Screenshot, Summary, Transcript
from app.errors import ApiError, NotFoundError
from app.services.projects import PROJECT_NOT_FOUND
from app.summarization import (
    Summarizer,
    SummarizerError,
    SummarizerRateLimited,
    SummarizerTimeout,
    SummaryImage,
    SummaryRequest,
)
from app.summarization.prompt import (
    PromptImage,
    ScreenshotInput,
    TranscriptInput,
    build_request,
    downscale_image,
    oldest_first,
    prepare_transcripts,
    select_screenshots,
)
from app.summarization.render import RenderContext, render_document
from app.telemetry.summary import SummaryMetricStatus, SummaryTrack, track_summary

PENDING, RUNNING, SUCCEEDED, FAILED = "pending", "running", "succeeded", "failed"
ACTIVE_STATUSES = (PENDING, RUNNING)
SummaryErrorCode = Literal["provider_error", "provider_timeout", "interrupted", "internal_error"]
SUMMARY_NOT_FOUND = "Summary not found"

SessionFactory = async_sessionmaker[AsyncSession]
logger = logging.getLogger(__name__)


# --- API operations -----------------------------------------------------------------------


async def _active_summary(session: AsyncSession, project_id: uuid.UUID) -> Summary | None:
    return await session.scalar(
        select(Summary).where(Summary.project_id == project_id, Summary.status.in_(ACTIVE_STATUSES))
    )


async def _require_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError(PROJECT_NOT_FOUND)
    return project


async def start_summary(
    session: AsyncSession, project_id: uuid.UUID, provider: str
) -> tuple[Summary, bool]:
    """`(summary, created)`: a new `pending` job, or the active one (AC4). 404 / 409 (AC1)."""
    await _require_project(session, project_id)
    count = await session.scalar(
        select(func.count(Transcript.id)).where(Transcript.project_id == project_id)
    )
    if not count:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "The project has no transcripts to summarize",
            "no_transcripts",
        )
    active = await _active_summary(session, project_id)
    if active is not None:
        return active, False
    summary = Summary(
        project_id=project_id,
        status=PENDING,
        provider=provider,
        truncated=False,
        transcript_count=0,
        image_count=0,
    )
    session.add(summary)
    try:
        await session.commit()
    except IntegrityError:  # a concurrent POST won the partial unique index
        await session.rollback()
        active = await _active_summary(session, project_id)
        if active is None:
            raise
        return active, False
    logger.info(
        "summary created",
        extra={"summary_id": str(summary.id), "project_id": str(project_id), "provider": provider},
    )
    return summary, True


async def latest_summary(session: AsyncSession, project_id: uuid.UUID) -> Summary:
    """The most recently created summary of the project (AC2)."""
    await _require_project(session, project_id)
    summary = await session.scalar(
        select(Summary)
        .where(Summary.project_id == project_id)
        .order_by(Summary.created_at.desc(), Summary.id.desc())
        .limit(1)
    )
    if summary is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, SUMMARY_NOT_FOUND, "summary_not_found")
    return summary


async def downloadable_summary(
    session: AsyncSession, project_id: uuid.UUID, summary_id: uuid.UUID
) -> Summary:
    """A succeeded summary of this project; 404 unknown / other project, 409 not ready (AC3)."""
    summary = await session.get(Summary, summary_id)
    if summary is None or summary.project_id != project_id:
        raise ApiError(status.HTTP_404_NOT_FOUND, SUMMARY_NOT_FOUND, "summary_not_found")
    if summary.status != SUCCEEDED or summary.html is None:
        raise ApiError(
            status.HTTP_409_CONFLICT, "The summary is not ready yet", "summary_not_ready"
        )
    return summary


async def latest_succeeded_html(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """HTML of the newest succeeded summary, for the ZIP export (AC5, AC12)."""
    return await session.scalar(
        select(Summary.html)
        .where(Summary.project_id == project_id, Summary.status == SUCCEEDED)
        .order_by(Summary.created_at.desc(), Summary.id.desc())
        .limit(1)
    )


def summary_html_bytes(html: str) -> bytes:
    """The exact bytes of `summary.html`, shared by the download and the ZIP export."""
    return html.encode("utf-8")


# --- Background job -----------------------------------------------------------------------


@dataclass(frozen=True)
class LoadedJob:
    project_id: uuid.UUID
    project_name: str
    request: SummaryRequest
    images: dict[int, SummaryImage]
    truncated: bool
    input_chars: int


def schedule_summary(
    tasks: set[asyncio.Task[None]],
    factory: SessionFactory,
    summarizer: Summarizer,
    summary: Summary,
    settings: Settings,
) -> None:
    """Start the job; `tasks` keeps a strong reference until it is done."""
    task = asyncio.create_task(
        run_summary_job(factory, summarizer, summary.id, summary.project_id, settings),
        name=f"summary-{summary.id}",
    )
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def run_summary_job(
    factory: SessionFactory,
    summarizer: Summarizer,
    summary_id: uuid.UUID,
    project_id: uuid.UUID,
    settings: Settings,
) -> None:
    """Never raises (except on cancellation): every failure ends as a `failed` row."""
    fields = {"summary_id": str(summary_id), "project_id": str(project_id)}
    with track_summary(project_id, summary_id, summarizer.name) as track:
        try:
            await _run(factory, summarizer, summary_id, settings, track, fields)
        except asyncio.CancelledError:
            track.cancelled = True
            raise
        logger.info(
            "summary_finished",
            extra={
                **fields,
                "provider": summarizer.name,
                "status": track.status.value,
                "duration_ms": round(track.elapsed * 1000, 2),
            },
        )


async def _run(
    factory: SessionFactory,
    summarizer: Summarizer,
    summary_id: uuid.UUID,
    settings: Settings,
    track: SummaryTrack,
    fields: dict[str, str],
) -> None:
    error_code: SummaryErrorCode
    try:
        job = await _load_and_mark_running(factory, summary_id, settings)
        if job is None:  # deleted with its project before the job started
            track.status = SummaryMetricStatus.INTERNAL_ERROR
            return
        track.annotate(
            transcript_count=len(job.request.transcript_titles),
            image_count=len(job.images),
            input_chars=job.input_chars,
            truncated=job.truncated,
        )
        logger.info(
            "summary_started",
            extra={
                **fields,
                "provider": summarizer.name,
                "transcript_count": len(job.request.transcript_titles),
                "image_count": len(job.images),
                "input_chars": job.input_chars,
                "truncated": job.truncated,
            },
        )
        result = await asyncio.wait_for(
            summarizer.summarize(job.request), settings.summary_timeout_seconds
        )
        html = render_document(
            result.fragment,
            job.images,
            RenderContext(job.project_name, summarizer.name, result.model, utcnow(), job.truncated),
        )
        track.annotate(model=result.model, output_bytes=len(summary_html_bytes(html)))
        await _store_success(factory, summary_id, job.project_id, html, result.model)
        track.status = SummaryMetricStatus.SUCCESS
        return
    except (TimeoutError, SummarizerTimeout):
        track.status, error_code = SummaryMetricStatus.TIMEOUT, "provider_timeout"
    except SummarizerRateLimited:
        track.status, error_code = SummaryMetricStatus.RATE_LIMITED, "provider_error"
    except SummarizerError:
        track.status, error_code = SummaryMetricStatus.PROVIDER_ERROR, "provider_error"
    except Exception:
        # Class + stack frames only; the log formatter never includes the exception message.
        logger.error("summary job crashed", extra=fields, exc_info=True)
        track.status, error_code = SummaryMetricStatus.INTERNAL_ERROR, "internal_error"
    try:
        await _store_failure(factory, summary_id, error_code)
    except Exception:  # e.g. the database is down; startup recovery fixes the row later
        logger.error("summary failure not stored", extra=fields, exc_info=True)


async def _load_and_mark_running(
    factory: SessionFactory, summary_id: uuid.UUID, settings: Settings
) -> LoadedJob | None:
    async with factory() as session:
        summary = await session.get(Summary, summary_id)
        if summary is None:
            return None
        project = await session.get(Project, summary.project_id)
        if project is None:  # pragma: no cover - the FK cascade deletes the summary too
            return None
        summary.status, summary.started_at = RUNNING, utcnow()
        job = await _load_job(session, project, settings)
        summary.truncated = job.truncated
        summary.transcript_count = len(job.request.transcript_titles)
        summary.image_count = len(job.images)
        await session.commit()
        return job


async def _load_job(session: AsyncSession, project: Project, settings: Settings) -> LoadedJob:
    rows = await session.scalars(select(Transcript).where(Transcript.project_id == project.id))
    transcripts = [
        TranscriptInput(t.title, t.text, t.language, t.created_at, t.id) for t in rows.all()
    ]
    prepared = prepare_transcripts(transcripts, settings.summary_max_chars)
    shots = await session.scalars(select(Screenshot).where(Screenshot.project_id == project.id))
    screenshots = [
        ScreenshotInput(s.id, s.transcript_id, s.filename, s.created_at) for s in shots.all()
    ]
    images, images_cut = await _prepare_images(session, screenshots, transcripts, settings)
    truncated = prepared.truncated or images_cut
    request = build_request(project.name, prepared, images, truncated)
    return LoadedJob(
        project_id=project.id,
        project_name=project.name,
        request=request,
        images={item.image.n: item.image for item in images},
        truncated=truncated,
        input_chars=prepared.input_chars,
    )


async def _prepare_images(
    session: AsyncSession,
    screenshots: list[ScreenshotInput],
    transcripts: list[TranscriptInput],
    settings: Settings,
) -> tuple[list[PromptImage], bool]:
    """Up to `SUMMARY_MAX_IMAGES` decodable screenshots, numbered in upload order.

    Returns `(images, cut)`: `cut` is true when candidates were left out because of the cap.
    """
    transcript_n = {t.id: n for n, t in enumerate(oldest_first(transcripts), start=1)}
    candidates = select_screenshots(screenshots, set(transcript_n))
    chosen: list[tuple[ScreenshotInput, str, bytes]] = []
    for index, shot in enumerate(candidates):
        if len(chosen) >= settings.summary_max_images:
            return _number(chosen, transcript_n), index < len(candidates)
        data = await session.scalar(select(Screenshot.data).where(Screenshot.id == shot.id))
        prepared = await asyncio.to_thread(
            downscale_image, data or b"", settings.summary_image_max_px
        )
        if prepared is not None:
            chosen.append((shot, *prepared))
    return _number(chosen, transcript_n), False


def _number(
    chosen: list[tuple[ScreenshotInput, str, bytes]], transcript_n: dict[uuid.UUID, int]
) -> list[PromptImage]:
    ordered = sorted(chosen, key=lambda item: (item[0].created_at, str(item[0].id)))
    return [
        PromptImage(
            SummaryImage(n, mime, data),
            shot.filename,
            transcript_n.get(shot.transcript_id) if shot.transcript_id else None,
        )
        for n, (shot, mime, data) in enumerate(ordered, start=1)
    ]


async def _store_success(
    factory: SessionFactory, summary_id: uuid.UUID, project_id: uuid.UUID, html: str, model: str
) -> None:
    """Mark succeeded and delete the project's older summaries in one transaction (AC5)."""
    async with factory() as session:
        summary = await session.get(Summary, summary_id)
        if summary is None:  # the project was deleted while the provider worked
            return
        summary.status, summary.html, summary.model = SUCCEEDED, html, model
        summary.error_code, summary.finished_at = None, utcnow()
        await session.execute(
            delete(Summary).where(Summary.project_id == project_id, Summary.id != summary_id)
        )
        await session.commit()


async def _store_failure(
    factory: SessionFactory, summary_id: uuid.UUID, error_code: SummaryErrorCode
) -> None:
    async with factory() as session:
        await session.execute(
            update(Summary)
            .where(Summary.id == summary_id)
            .values(status=FAILED, error_code=error_code, finished_at=utcnow())
        )
        await session.commit()


# --- Lifecycle ----------------------------------------------------------------------------


async def recover_interrupted(factory: SessionFactory) -> int:
    """Startup (AC18): jobs left `pending`/`running` by a dead process become `interrupted`."""
    async with factory() as session:
        result = await session.execute(
            update(Summary)
            .where(Summary.status.in_(ACTIVE_STATUSES))
            .values(status=FAILED, error_code="interrupted", finished_at=utcnow())
        )
        await session.commit()
    count = int(result.rowcount)  # type: ignore[attr-defined]
    logger.info("summary recovery finished", extra={"interrupted_count": count})
    return count


async def cancel_summary_tasks(tasks: set[asyncio.Task[None]]) -> None:
    """Shutdown: cancel running jobs (the next startup marks them `interrupted`)."""
    pending = list(tasks)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
