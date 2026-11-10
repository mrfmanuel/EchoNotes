"""#10 slug rules (US-01): pure `slugify`, suffixing and the DB-backed `unique_slug`."""

import re

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, Transcript
from app.services.slugs import next_free_slug, slugify, unique_slug

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Notes", "notes"),
        ("Clase de Física", "clase-de-fisica"),
        ("  Ünïcödé   Ñandú  ", "unicode-nandu"),
        ("Q3 / Planning -- 2026!", "q3-planning-2026"),
        ("---a___b---", "a-b"),
        ("CamelCase", "camelcase"),
    ],
)
def test_slugify_lowercases_transliterates_and_collapses_separators(
    name: str, expected: str
) -> None:
    assert slugify(name) == expected


@pytest.mark.parametrize("name", ["!!!", "   ", "", "日本語", "---"])
def test_slugify_falls_back_to_project_when_empty(name: str) -> None:
    assert slugify(name) == "project"


def test_slugify_uses_custom_fallback() -> None:
    assert slugify("???", fallback="transcript") == "transcript"


@pytest.mark.parametrize(
    "name", ["Clase de Física", "a" * 100, " -x- ", "Ärger & Öl", "x" * 300 + "!", "1 2 3"]
)
def test_slugify_result_matches_openapi_pattern(name: str) -> None:
    slug = slugify(name)
    assert SLUG_PATTERN.match(slug)
    assert len(slug) <= 200


def test_next_free_slug_appends_lowest_free_suffix() -> None:
    assert next_free_slug("notes", set()) == "notes"
    assert next_free_slug("notes", {"notes"}) == "notes-2"
    assert next_free_slug("notes", {"notes", "notes-2"}) == "notes-3"
    assert next_free_slug("notes", {"notes", "notes-3"}) == "notes-2"


@pytest.mark.anyio
async def test_unique_slug_skips_taken_slugs_notes_and_notes_2(session: AsyncSession) -> None:
    session.add_all([Project(name="Notes", slug="notes"), Project(name="Notes", slug="notes-2")])
    await session.commit()

    assert await unique_slug(session, Project.slug, "Notes") == "notes-3"


@pytest.mark.anyio
async def test_unique_slug_ignores_slugs_that_only_share_a_prefix(session: AsyncSession) -> None:
    session.add_all(
        [
            Project(name="Notes extra", slug="notes-extra"),
            Project(name="Notesy", slug="notesy"),
            Project(name="Notes 2b", slug="notes-2b"),
        ]
    )
    await session.commit()

    assert await unique_slug(session, Project.slug, "Notes") == "notes"


@pytest.mark.anyio
async def test_unique_slug_can_be_scoped_to_a_project(session: AsyncSession) -> None:
    first, second = Project(name="A", slug="a"), Project(name="B", slug="b")
    session.add_all(
        [
            first,
            second,
            Transcript(project=first, title="Lecture", slug="lecture", provider="fake"),
        ]
    )
    await session.commit()

    in_first = await unique_slug(
        session, Transcript.slug, "Lecture", Transcript.project_id == first.id
    )
    in_second = await unique_slug(
        session, Transcript.slug, "Lecture", Transcript.project_id == second.id
    )

    assert (in_first, in_second) == ("lecture-2", "lecture")
