"""add transcription_queue table

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-04-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: str | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pre-create the enum idempotently so re-runs after partial failure
    # don't crash. ``create_type=False`` on the column reference below
    # prevents ``create_table`` from emitting a second CREATE TYPE.
    sa.Enum(
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        name="queue_status",
    ).create(op.get_bind(), checkfirst=True)

    queue_status_col = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        name="queue_status",
        create_type=False,
    )

    op.create_table(
        "transcription_queue",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("episode_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("show_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            queue_status_col,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "ignored",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("whisper_model", sa.String(50), nullable=False),
        sa.ForeignKeyConstraint(
            ["episode_id"], ["episodes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["show_id"], ["shows.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("episode_id", name="uq_transcription_queue_episode"),
    )

    op.create_index(
        "ix_transcription_queue_status",
        "transcription_queue",
        ["status"],
    )
    op.create_index(
        "ix_transcription_queue_position",
        "transcription_queue",
        ["position"],
    )
    op.create_index(
        "ix_transcription_queue_show_id",
        "transcription_queue",
        ["show_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transcription_queue_show_id", table_name="transcription_queue")
    op.drop_index("ix_transcription_queue_position", table_name="transcription_queue")
    op.drop_index("ix_transcription_queue_status", table_name="transcription_queue")
    op.drop_table("transcription_queue")
    sa.Enum(name="queue_status").drop(op.get_bind(), checkfirst=True)
