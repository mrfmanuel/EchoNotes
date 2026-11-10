"""initial schema: project, transcript, screenshot

Revision ID: 0001
Revises:
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_project"),
        sa.UniqueConstraint("slug", name="uq_project_slug"),
    )
    op.create_table(
        "transcript",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_transcript"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name="fk_transcript_project_id_project",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_transcript_project_id", "transcript", ["project_id"])
    op.create_table(
        "screenshot",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_screenshot"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name="fk_screenshot_project_id_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcript.id"],
            name="fk_screenshot_transcript_id_transcript",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_screenshot_project_id", "screenshot", ["project_id"])
    op.create_index("ix_screenshot_transcript_id", "screenshot", ["transcript_id"])


def downgrade() -> None:
    op.drop_index("ix_screenshot_transcript_id", table_name="screenshot")
    op.drop_index("ix_screenshot_project_id", table_name="screenshot")
    op.drop_table("screenshot")
    op.drop_index("ix_transcript_project_id", table_name="transcript")
    op.drop_table("transcript")
    op.drop_table("project")
