"""#15 / US-16: the pure export tree builder (file names, duplicate slugs, README)."""

import re
import uuid
from datetime import UTC, datetime

from app.db.models import Project, Screenshot, Transcript
from app.services.export import EMPTY_PROJECT_NOTE, build_plan, screenshot_file_name
from tests.project_utils import at

EXPORTED_AT = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
LINK = re.compile(r"\]\(([^)]+)\)")


def _project() -> Project:
    return Project(id=uuid.uuid4(), name="Física | 101", slug="fisica-101")


def _transcript(slug: str, minute: int, title: str = "Notes") -> Transcript:
    return Transcript(
        id=uuid.uuid4(),
        title=title,
        slug=slug,
        text="text",
        language=None,
        duration_seconds=None,
        provider="fake",
        created_at=at(minute),
    )


def _screenshot(
    filename: str,
    minute: int,
    content_type: str = "image/png",
    transcript_id: uuid.UUID | None = None,
) -> Screenshot:
    return Screenshot(
        id=uuid.uuid4(),
        filename=filename,
        content_type=content_type,
        size_bytes=1,
        transcript_id=transcript_id,
        created_at=at(minute),
    )


def test_duplicate_transcript_slugs_get_numeric_suffixes_oldest_first() -> None:
    newest, middle, oldest = (
        _transcript("notes", 3),
        _transcript("notes", 2),
        _transcript("notes", 1),
    )

    plan = build_plan(_project(), [newest, middle, oldest], [], EXPORTED_AT)

    paths = [(f.transcript, f.md_path, f.txt_path) for f in plan.transcripts]
    assert paths == [
        (oldest, "transcripts/notes.md", "transcripts/notes.txt"),
        (middle, "transcripts/notes-2.md", "transcripts/notes-2.txt"),
        (newest, "transcripts/notes-3.md", "transcripts/notes-3.txt"),
    ]


def test_duplicate_suffix_never_collides_with_an_existing_suffixed_slug() -> None:
    transcripts = [_transcript("notes", 1), _transcript("notes-2", 2), _transcript("notes", 3)]

    plan = build_plan(_project(), transcripts, [], EXPORTED_AT)

    md_paths = [f.md_path for f in plan.transcripts]
    assert md_paths == ["transcripts/notes.md", "transcripts/notes-2.md", "transcripts/notes-3.md"]


def test_screenshot_names_are_numbered_by_created_at_with_slug_and_type_extension() -> None:
    shots = [
        _screenshot("Último Slide.PNG", 2),
        _screenshot("photo.jpeg", 1, "image/jpeg"),
        _screenshot("!!!.webp", 3, "image/webp"),
        _screenshot("diagram.gif", 4, "image/png"),  # extension comes from the stored type
    ]

    plan = build_plan(_project(), [], shots, EXPORTED_AT)

    assert [f.path for f in plan.screenshots] == [
        "screenshots/01-photo.jpg",
        "screenshots/02-ultimo-slide.png",
        "screenshots/03-screenshot.webp",
        "screenshots/04-diagram.png",
    ]


def test_screenshot_name_ignores_directories_in_the_stored_filename() -> None:
    assert screenshot_file_name(7, _screenshot("C:\\tmp\\a b.png", 1)) == "07-a-b.png"


def test_empty_project_readme_states_it_is_empty() -> None:
    plan = build_plan(_project(), [], [], EXPORTED_AT)

    assert plan.readme.startswith("# Física | 101\n\nExported: 2026-11-10 (UTC)\n")
    assert EMPTY_PROJECT_NOTE in plan.readme
    assert (plan.transcripts, plan.screenshots) == ([], [])


def test_readme_indexes_every_file_with_relative_links() -> None:
    transcript = _transcript("lecture", 1, title="Lecture | part 1")
    shot = _screenshot("slide.png", 2, transcript_id=transcript.id)

    plan = build_plan(_project(), [transcript], [shot], EXPORTED_AT)

    expected = {
        "transcripts/lecture.md",
        "transcripts/lecture.txt",
        "screenshots/01-slide.png",
    }
    assert set(LINK.findall(plan.readme)) == expected
    assert "Lecture \\| part 1" in plan.readme  # table cell escaped
    assert (
        "| 1 | [01-slide.png](screenshots/01-slide.png) | [lecture.md](transcripts/lecture.md) |"
        in plan.readme
    )
    assert EMPTY_PROJECT_NOTE not in plan.readme
    assert plan.root == "fisica-101"


def test_readme_says_no_screenshots_when_only_transcripts_exist() -> None:
    plan = build_plan(_project(), [_transcript("a", 1)], [], EXPORTED_AT)

    assert "No screenshots." in plan.readme
    assert "No transcripts." not in plan.readme
