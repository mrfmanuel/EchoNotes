"""Project ZIP export (US-16). Built in a spooled temp file and streamed; never persisted.

Layout (everything under `<project-slug>/`):

    README.md                          index with relative links
    transcripts/<slug>.md|.txt         same bytes as the #13 downloads
    screenshots/<nn>-<name>.<ext>      nn = 1-based, oldest first
    summary.html                       only when the project has a succeeded AI summary (US-22)
"""

import logging
import uuid
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import IO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Screenshot, Transcript
from app.errors import NotFoundError
from app.services.images import IMAGE_EXTENSIONS
from app.services.projects import PROJECT_NOT_FOUND
from app.services.slugs import next_free_slug, slugify
from app.services.summaries import latest_succeeded_html, summary_html_bytes
from app.services.transcript_format import format_duration, render_markdown, render_text
from app.telemetry import track_export

TRANSCRIPT_FALLBACK = "transcript"
SCREENSHOT_FALLBACK = "screenshot"
# Exports up to this size stay in memory; larger ones spill to an anonymous temp file.
SPOOL_MAX_MEMORY_BYTES = 16 * 1024 * 1024
STREAM_CHUNK_BYTES = 64 * 1024
EMPTY_PROJECT_NOTE = "This project is empty: it has no transcripts and no screenshots."
SUMMARY_PATH = "summary.html"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptFiles:
    transcript: Transcript
    md_path: str
    txt_path: str


@dataclass(frozen=True)
class ScreenshotFile:
    screenshot: Screenshot
    path: str


@dataclass
class ExportPlan:
    """Every path in the ZIP, relative to the `<slug>/` root, plus the README text."""

    root: str
    readme: str = ""
    transcripts: list[TranscriptFiles] = field(default_factory=list)
    screenshots: list[ScreenshotFile] = field(default_factory=list)
    summary_html: str | None = None  # written as `summary.html` when set


def _oldest_first[T: (Transcript, Screenshot)](items: Sequence[T]) -> list[T]:
    return sorted(items, key=lambda item: (item.created_at, str(item.id)))


def plan_transcripts(transcripts: Sequence[Transcript]) -> list[TranscriptFiles]:
    """One `.md` + `.txt` per transcript; duplicate slugs get `-2`, `-3`, ... (oldest first)."""
    taken: set[str] = set()
    planned: list[TranscriptFiles] = []
    for transcript in _oldest_first(transcripts):
        base = slugify(transcript.slug or "", TRANSCRIPT_FALLBACK)
        name = next_free_slug(base, taken)
        taken.add(name)
        planned.append(
            TranscriptFiles(transcript, f"transcripts/{name}.md", f"transcripts/{name}.txt")
        )
    return planned


def screenshot_file_name(index: int, screenshot: Screenshot) -> str:
    """`<nn>-<slug of the original name without extension>.<ext from the content type>`."""
    stem = PurePosixPath(screenshot.filename.replace("\\", "/")).stem
    name = slugify(stem, SCREENSHOT_FALLBACK)
    return f"{index:02d}-{name}.{IMAGE_EXTENSIONS[screenshot.content_type]}"


def plan_screenshots(screenshots: Sequence[Screenshot]) -> list[ScreenshotFile]:
    return [
        ScreenshotFile(shot, f"screenshots/{screenshot_file_name(i, shot)}")
        for i, shot in enumerate(_oldest_first(screenshots), start=1)
    ]


def _cell(value: str) -> str:
    """Make free text safe inside a Markdown table cell."""
    return " ".join(value.split()).replace("\\", "\\\\").replace("|", "\\|")


def _transcript_table(files: list[TranscriptFiles]) -> list[str]:
    if not files:
        return ["No transcripts."]
    lines = ["| Title | Date | Language | Duration | Files |", "|---|---|---|---|---|"]
    for item in files:
        t = item.transcript
        links = f"[{PurePosixPath(item.md_path).name}]({item.md_path}) · "
        links += f"[{PurePosixPath(item.txt_path).name}]({item.txt_path})"
        lines.append(
            f"| {_cell(t.title)} | {t.created_at.astimezone(UTC).date().isoformat()} "
            f"| {t.language or 'unknown'} | {format_duration(t.duration_seconds)} | {links} |"
        )
    return lines


def _screenshot_table(files: list[ScreenshotFile], transcripts: list[TranscriptFiles]) -> list[str]:
    if not files:
        return ["No screenshots."]
    md_by_id = {item.transcript.id: item.md_path for item in transcripts}
    lines = ["| # | Image | Linked transcript |", "|---|---|---|"]
    for index, item in enumerate(files, start=1):
        name = PurePosixPath(item.path).name
        transcript_id = item.screenshot.transcript_id
        linked = md_by_id.get(transcript_id) if transcript_id else None
        linked_cell = f"[{PurePosixPath(linked).name}]({linked})" if linked else "-"
        lines.append(f"| {index} | [{name}]({item.path}) | {linked_cell} |")
    return lines


def render_readme(
    project_name: str,
    exported_at: datetime,
    transcripts: list[TranscriptFiles],
    screenshots: list[ScreenshotFile],
    has_summary: bool = False,
) -> str:
    heading = " ".join(project_name.split())
    date = exported_at.astimezone(UTC).date().isoformat()
    lines = [f"# {heading}", "", f"Exported: {date} (UTC)", ""]
    if has_summary:
        lines += ["## AI summary", "", f"[{SUMMARY_PATH}]({SUMMARY_PATH})", ""]
    if not transcripts and not screenshots:
        return "\n".join([*lines, EMPTY_PROJECT_NOTE, ""])
    lines += ["## Transcripts", "", *_transcript_table(transcripts), ""]
    lines += ["## Screenshots", "", *_screenshot_table(screenshots, transcripts), ""]
    return "\n".join(lines)


def build_plan(
    project: Project,
    transcripts: Sequence[Transcript],
    screenshots: Sequence[Screenshot],
    exported_at: datetime,
    summary_html: str | None = None,
) -> ExportPlan:
    """Pure: decide every file name and the README for a project export."""
    plan = ExportPlan(root=project.slug, summary_html=summary_html)
    plan.transcripts = plan_transcripts(transcripts)
    plan.screenshots = plan_screenshots(screenshots)
    plan.readme = render_readme(
        project.name,
        exported_at,
        plan.transcripts,
        plan.screenshots,
        has_summary=summary_html is not None,
    )
    return plan


def _zip_info(path: str, exported_at: datetime, compress: bool) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, exported_at.astimezone(UTC).timetuple()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    info.external_attr = 0o644 << 16
    return info


async def _load_image(session: AsyncSession, screenshot_id: uuid.UUID) -> bytes:
    data = await session.scalar(select(Screenshot.data).where(Screenshot.id == screenshot_id))
    return data or b""


async def write_zip(
    session: AsyncSession, plan: ExportPlan, exported_at: datetime, target: IO[bytes]
) -> None:
    """Write the planned files into `target`. Images are loaded one at a time."""
    with zipfile.ZipFile(target, "w") as archive:

        def add(path: str, data: str | bytes, compress: bool = True) -> None:
            archive.writestr(_zip_info(f"{plan.root}/{path}", exported_at, compress), data)

        add("README.md", plan.readme)
        for item in plan.transcripts:
            add(item.md_path, render_markdown(item.transcript))
            add(item.txt_path, render_text(item.transcript))
        for shot in plan.screenshots:
            # Images are already compressed; storing them is faster and as small.
            add(shot.path, await _load_image(session, shot.screenshot.id), compress=False)
        if plan.summary_html is not None:  # same bytes as the summary download (US-22 AC12)
            add(SUMMARY_PATH, summary_html_bytes(plan.summary_html))


async def _load_contents(
    session: AsyncSession, project_id: uuid.UUID
) -> tuple[Project, list[Transcript], list[Screenshot]]:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError(PROJECT_NOT_FOUND)
    transcripts = await session.scalars(
        select(Transcript).where(Transcript.project_id == project_id)
    )
    screenshots = await session.scalars(  # metadata only; bytes are loaded per file
        select(Screenshot).where(Screenshot.project_id == project_id)
    )
    return project, list(transcripts.all()), list(screenshots.all())


@dataclass(frozen=True)
class ExportArchive:
    filename: str
    size_bytes: int
    file: IO[bytes]

    def chunks(self) -> Iterator[bytes]:
        """Stream the archive and close (discard) the temp file afterwards."""
        try:
            self.file.seek(0)
            while chunk := self.file.read(STREAM_CHUNK_BYTES):
                yield chunk
        finally:
            self.file.close()

    def close(self) -> None:
        self.file.close()


async def export_project(session: AsyncSession, project_id: uuid.UUID) -> ExportArchive:
    """Build `<slug>.zip` in a spooled temp file (memory first, never a named file).

    Traced as `export.build` and counted in `echonotes.exports{status}` (#29)."""
    with track_export(project_id) as span:
        project, transcripts, screenshots = await _load_contents(session, project_id)
        summary_html = await latest_succeeded_html(session, project_id)
        exported_at = datetime.now(UTC)
        plan = build_plan(project, transcripts, screenshots, exported_at, summary_html)
        spool: IO[bytes] = SpooledTemporaryFile(max_size=SPOOL_MAX_MEMORY_BYTES)  # noqa: SIM115
        try:
            await write_zip(session, plan, exported_at, spool)
            size = spool.tell()
        except BaseException:
            spool.close()
            raise
        span.set_attributes(
            {
                "echonotes.transcript_count": len(plan.transcripts),
                "echonotes.screenshot_count": len(plan.screenshots),
                "echonotes.export.size_bytes": size,
            }
        )
    logger.info(
        "project exported",
        extra={
            "project_id": str(project_id),
            "transcript_count": len(plan.transcripts),
            "screenshot_count": len(plan.screenshots),
            "size_bytes": size,
        },
    )
    return ExportArchive(f"{plan.root}.zip", size, spool)
