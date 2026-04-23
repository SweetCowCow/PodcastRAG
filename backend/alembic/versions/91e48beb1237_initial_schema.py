"""initial_schema

Revision ID: 91e48beb1237
Revises:
Create Date: 2026-04-21

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "91e48beb1237"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


transcript_status = postgresql.ENUM(
    "pending",
    "processing",
    "completed",
    "failed",
    name="transcriptstatus",
    create_type=False,
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "CREATE TYPE transcriptstatus AS ENUM ('pending', 'processing', 'completed', 'failed')"
    )

    op.create_table(
        "shows",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("rss_url", sa.String(2048), nullable=False, unique=True),
        sa.Column("image_url", sa.String(2048), nullable=True),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "episodes",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "show_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("shows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("audio_url", sa.String(2048), nullable=False),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guid", sa.String(2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("show_id", "guid", name="uq_episode_show_guid"),
    )

    op.create_table(
        "transcripts",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "episode_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", transcript_status, nullable=False),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "transcript_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("transcripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("speaker", sa.String(200), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("transcript_segments")
    op.drop_table("transcripts")
    op.execute("DROP TYPE IF EXISTS transcriptstatus")
    op.drop_table("episodes")
    op.drop_table("shows")
    op.execute("DROP EXTENSION IF EXISTS vector")
