"""summaries: AI project summary jobs (US-22)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_WHERE = "status IN ('pending', 'running')"


def upgrade() -> None:
    op.create_table(
        "summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("transcript_count", sa.Integer(), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("html", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_summaries"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name="fk_summaries_project_id_project",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_summaries_project_id", "summaries", ["project_id"])
    op.create_index(
        "uq_summaries_active_project",
        "summaries",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_WHERE),
        sqlite_where=sa.text(ACTIVE_WHERE),
    )


def downgrade() -> None:
    op.drop_index("uq_summaries_active_project", table_name="summaries")
    op.drop_index("ix_summaries_project_id", table_name="summaries")
    op.drop_table("summaries")
