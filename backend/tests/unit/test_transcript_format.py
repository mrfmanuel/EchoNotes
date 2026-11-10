"""US-10 AC1/AC2/AC4: `.md` and `.txt` renderers shared by downloads (#13) and export (#15)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.db.models import Transcript
from app.services.transcript_format import (
    format_duration,
    metadata_line,
    render_markdown,
    render_text,
)


@dataclass
class FakeTranscript:
    title: str = "Lecture 1"
    text: str = "Hola mundo."
    language: str | None = "es"
    duration_seconds: float | None = 125.4
    created_at: datetime = datetime(2026, 11, 10, 9, 30, tzinfo=UTC)


def test_render_markdown_has_heading_metadata_blank_line_and_text() -> None:
    assert render_markdown(FakeTranscript()) == (
        "# Lecture 1\nDate: 2026-11-10 · Language: es · Duration: 2:05\n\nHola mundo.\n"
    )


def test_render_markdown_does_not_add_a_second_trailing_newline() -> None:
    assert render_markdown(FakeTranscript(text="Line\n")).endswith("\n\nLine\n")


def test_render_text_is_the_plain_text_only() -> None:
    assert render_text(FakeTranscript(text="Just text\nsecond line")) == "Just text\nsecond line"


def test_metadata_line_uses_unknown_for_missing_language_and_duration() -> None:
    transcript = FakeTranscript(language=None, duration_seconds=None)

    assert metadata_line(transcript) == "Date: 2026-11-10 · Language: unknown · Duration: unknown"


def test_metadata_line_date_is_created_at_in_utc() -> None:
    late_evening_minus_5 = datetime(2026, 11, 10, 21, 0, tzinfo=timezone(timedelta(hours=-5)))

    line = metadata_line(FakeTranscript(created_at=late_evening_minus_5))

    assert line.startswith("Date: 2026-11-11 ·")


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00"),
        (5, "0:05"),
        (59.6, "1:00"),
        (61, "1:01"),
        (3725, "62:05"),
        (None, "unknown"),
        (-1, "unknown"),
    ],
)
def test_format_duration_is_m_ss(seconds: float | None, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_renderers_accept_the_orm_model() -> None:
    transcript = Transcript(
        title="Notes",
        slug="notes",
        text="body",
        language="en",
        duration_seconds=9,
        provider="fake",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert render_markdown(transcript) == (
        "# Notes\nDate: 2026-01-02 · Language: en · Duration: 0:09\n\nbody\n"
    )
    assert render_text(transcript) == "body"
