"""Pydantic I/O models mirroring `openapi.yaml` components/schemas."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.db.models import PROJECT_NAME_MAX

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


class ProjectDetail(Project):
    transcripts: list[TranscriptSummary]
    screenshots: list[Screenshot]


def screenshot_image_url(screenshot_id: uuid.UUID) -> str:
    return f"/api/screenshots/{screenshot_id}/image"
