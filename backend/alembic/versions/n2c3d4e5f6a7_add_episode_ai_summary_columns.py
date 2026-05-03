"""add episode ai_summary columns

Revision ID: n2c3d4e5f6a7
Revises: m1b2c3d4e5f6
Create Date: 2026-05-03

Adds four columns to the `episodes` table for storing AI-generated summaries:
  - ai_summary               TEXT NULL
  - ai_summary_status        ENUM('pending','running','done','failed')
                             NOT NULL DEFAULT 'pending'
  - ai_summary_generated_at  TIMESTAMPTZ NULL
  - ai_summary_model         VARCHAR(100) NULL

All existing rows are initialised to status='pending'. No tasks are
enqueued — backfill is admin-triggered (D4 in the design doc).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "n2c3d4e5f6a7"
down_revision: str | None = "m1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SUMMARY_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "running",
    "done",
    "failed",
    name="ai_summary_status_enum",
    create_type=True,
)


def upgrade() -> None:
    SUMMARY_STATUS_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column("episodes", sa.Column("ai_summary", sa.Text(), nullable=True))
    op.add_column(
        "episodes",
        sa.Column(
            "ai_summary_status",
            SUMMARY_STATUS_ENUM,
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "episodes",
        sa.Column(
            "ai_summary_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "episodes",
        sa.Column("ai_summary_model", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("episodes", "ai_summary_model")
    op.drop_column("episodes", "ai_summary_generated_at")
    op.drop_column("episodes", "ai_summary_status")
    op.drop_column("episodes", "ai_summary")
    SUMMARY_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
