"""add transcription_queue.dispatched_at + partial index

Revision ID: z4a5b6c7d8e9
Revises: y3f4a5b6c7d8
Create Date: 2026-05-18

Part of change `celery-routing-and-dispatcher-fix` (B1 reviewer fix).

Adds `dispatched_at TIMESTAMPTZ NULLABLE` to `transcription_queue`. The
dispatcher uses this column as its own memo pad: after sending a Celery
task it sets `dispatched_at = NOW()` in the same transaction, so the
next dispatcher tick (every second) won't re-select the same pending
row and double-dispatch. Worker entry and terminal transitions clear
it back to NULL.

A partial index on `(status, dispatched_at) WHERE status='pending'`
keeps the dispatcher's primary query
`WHERE status='pending' AND dispatched_at IS NULL ORDER BY position`
index-only and fast even on large queues.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "z4a5b6c7d8e9"
down_revision: str | None = "y3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAME = "ix_transcription_queue_pending_dispatched_at"


def upgrade() -> None:
    op.add_column(
        "transcription_queue",
        sa.Column(
            "dispatched_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=None,
        ),
    )
    # Partial index: only pending rows matter to the dispatcher SELECT.
    op.create_index(
        INDEX_NAME,
        "transcription_queue",
        ["dispatched_at", "position"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        INDEX_NAME,
        table_name="transcription_queue",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_column("transcription_queue", "dispatched_at")
