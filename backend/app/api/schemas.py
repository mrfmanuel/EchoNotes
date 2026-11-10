"""Pydantic I/O models mirroring `openapi.yaml` components/schemas."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.db.models import PROJECT_NAME_MAX, TRANSCRIPT_TITLE_MAX
from app.db.models import Screenshot as ScreenshotRow

ProjectName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=PROJECT_NAME_MAX)
]


class ProjectCreate(BaseModel):
    name: ProjectName


class ProjectUpdate(ProjectCreate):
    pass


class Project(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    transcript_count: int
    screenshot_count: int
    created_at: datetime
    updated_at: datetime


class TranscriptSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    slug: str
    language: str | None
    duration_seconds: float | None
    provider: str
    created_at: datetime
    updated_at: datetime


class Transcript(TranscriptSummary):
    text: str
    source_filename: str | None


TranscriptTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TRANSCRIPT_TITLE_MAX)
]


class TranscriptUpdate(BaseModel):
    """PATCH body (US-08): `title` (trimmed, 1-200) and/or `text`; at least one, never null."""

    title: TranscriptTitle | None = None
    text: str | None = None

    @model_validator(mode="after")
    def _at_least_one_non_null_field(self) -> "TranscriptUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one of: title, text")
        null_fields = sorted(f for f in self.model_fields_set if getattr(self, f) is None)
        if null_fields:
            raise ValueError(f"Fields must not be null: {', '.join(null_fields)}")
        return self


class Error(BaseModel):
    detail: str
    code: str


class Screenshot(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    transcript_id: uuid.UUID | None
    filename: str
    content_type: str
    size_bytes: int
    image_url: str
    created_at: datetime


class ScreenshotUpdate(BaseModel):
    """PATCH body: a transcript ID links the screenshot, `null` unlinks it (US-14)."""

    transcript_id: uuid.UUID | None = None


class ProjectDetail(Project):
    transcripts: list[TranscriptSummary]
    screenshots: list[Screenshot]


def screenshot_image_url(screenshot_id: uuid.UUID) -> str:
    return f"/api/screenshots/{screenshot_id}/image"


def to_screenshot(screenshot: ScreenshotRow) -> Screenshot:
    """Response model for a screenshot row (metadata only, never the bytes)."""
    return Screenshot(
        id=screenshot.id,
        project_id=screenshot.project_id,
        transcript_id=screenshot.transcript_id,
        filename=screenshot.filename,
        content_type=screenshot.content_type,
        size_bytes=screenshot.size_bytes,
        image_url=screenshot_image_url(screenshot.id),
        created_at=screenshot.created_at,
    )
