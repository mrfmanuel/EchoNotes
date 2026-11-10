"""URL-safe slugs (US-01). Reused for transcripts (#12) and export folder names (#15)."""

import re
import unicodedata
from typing import Any

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

DEFAULT_FALLBACK = "project"
# Room for a "-<n>" suffix inside the 220-char slug column.
SLUG_BASE_MAX = 200

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SUFFIX = re.compile(r"^-([1-9][0-9]*)$")


def slugify(value: str, fallback: str = DEFAULT_FALLBACK) -> str:
    """Lowercase ASCII slug matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`.

    Accents are transliterated (`Física` → `fisica`), every run of other characters becomes
    one `-`, and an empty result falls back to `fallback`.
    """
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = _NON_ALNUM.sub("-", ascii_text.lower()).strip("-")
    slug = slug[:SLUG_BASE_MAX].rstrip("-")
    return slug or fallback


def next_free_slug(base: str, taken: set[str]) -> str:
    """`base` if free, otherwise `base-2`, `base-3`, ... (the first free one)."""
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _is_candidate(slug: str, base: str) -> bool:
    return slug == base or bool(slug.startswith(base) and _SUFFIX.match(slug[len(base) :]))


async def unique_slug(
    session: AsyncSession,
    column: InstrumentedAttribute[str],
    value: str,
    *scope: ColumnElement[Any],
    fallback: str = DEFAULT_FALLBACK,
) -> str:
    """Slug for `value` that is not yet used in `column` (optionally within a `scope` filter).

    The DB unique constraint stays the final guard; callers retry on `IntegrityError`.
    """
    base = slugify(value, fallback)
    query = select(column).where(column.startswith(base, autoescape=True), *scope)
    taken = {slug for slug in (await session.scalars(query)).all() if _is_candidate(slug, base)}
    return next_free_slug(base, taken)
