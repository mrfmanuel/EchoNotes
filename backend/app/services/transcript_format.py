"""`.md` / `.txt` renderers for a transcript (US-10). Pure functions, reused by the export (#15).

Download (#13) and export (#15) both call these, so the files are byte-identical.
"""

from datetime import UTC, datetime
from typing import Protocol

UNKNOWN = "unknown"
SEPARATOR = " · "


class RenderableTranscript(Protocol):
    """The transcript fields the renderers read (satisfied by the `Transcript` model)."""

    @property
    def title(self) -> str: ...

    @property
    def text(self) -> str: ...

    @property
    def language(self) -> str | None: ...

    @property
    def duration_seconds(self) -> float | None: ...

    @property
    def created_at(self) -> datetime: ...


def format_duration(seconds: float | None) -> str:
    """`m:ss` (minutes are not capped at 59), rounded to whole seconds; `unknown` if missing."""
    if seconds is None or seconds < 0:
        return UNKNOWN
    total = round(seconds)
    return f"{total // 60}:{total % 60:02d}"


def metadata_line(transcript: RenderableTranscript) -> str:
    """`Date: YYYY-MM-DD · Language: <code|unknown> · Duration: m:ss|unknown` (date in UTC)."""
    date = transcript.created_at.astimezone(UTC).date().isoformat()
    language = transcript.language or UNKNOWN
    duration = format_duration(transcript.duration_seconds)
    return SEPARATOR.join((f"Date: {date}", f"Language: {language}", f"Duration: {duration}"))


def render_markdown(transcript: RenderableTranscript) -> str:
    """`# <title>`, the metadata line, a blank line and the text (ending with a newline)."""
    body = transcript.text
    if not body.endswith("\n"):
        body += "\n"
    return f"# {transcript.title}\n{metadata_line(transcript)}\n\n{body}"


def render_text(transcript: RenderableTranscript) -> str:
    """The plain transcript text only, unchanged."""
    return transcript.text
