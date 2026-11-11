"""ORM models. See docs/architecture.md#data-model."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow

PROJECT_NAME_MAX = 100
TRANSCRIPT_TITLE_MAX = 200
SLUG_MAX = 220
# Summary statuses that block a new job (one active job per project, US-22 AC4).
ACTIVE_SUMMARY_WHERE = "status IN ('pending', 'running')"


def _created_at() -> Mapped[datetime]:
    return mapped_column(UTCDateTime(), default=utcnow, server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, server_default=func.now())


class Project(Base):
    __tablename__ = "project"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX))
    slug: Mapped[str] = mapped_column(String(SLUG_MAX), unique=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    transcripts: Mapped[list["Transcript"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    screenshots: Mapped[list["Screenshot"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class Transcript(Base):
    __tablename__ = "transcript"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(TRANSCRIPT_TITLE_MAX))
    slug: Mapped[str] = mapped_column(String(SLUG_MAX))
    text: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str | None] = mapped_column(String(16))
    duration_seconds: Mapped[float | None]
    provider: Mapped[str] = mapped_column(String(32))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    project: Mapped[Project] = relationship(back_populates="transcripts")
    screenshots: Mapped[list["Screenshot"]] = relationship(
        back_populates="transcript", passive_deletes=True
    )


class Screenshot(Base):
    __tablename__ = "screenshot"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    transcript_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transcript.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    # Image bytes (bytea on Postgres). Deferred so list queries only load metadata.
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    created_at: Mapped[datetime] = _created_at()

    project: Mapped[Project] = relationship(back_populates="screenshots")
    transcript: Mapped[Transcript | None] = relationship(back_populates="screenshots")


class Summary(Base):
    """An AI project summary job and, once `succeeded`, its sanitized HTML (US-22)."""

    __tablename__ = "summaries"
    __table_args__ = (
        # At most one pending/running job per project, even under concurrent POSTs.
        Index(
            "uq_summaries_active_project",
            "project_id",
            unique=True,
            postgresql_where=text(ACTIVE_SUMMARY_WHERE),
            sqlite_where=text(ACTIVE_SUMMARY_WHERE),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16))  # pending|running|succeeded|failed
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(32))
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    transcript_count: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    html: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
