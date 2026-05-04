"""add ai_summary_started_at and ai_summary_error to episodes

Revision ID: o3d4e5f6a7b8
Revises: n2c3d4e5f6a7
Create Date: 2026-05-04

Adds two columns required by the cron-tick stale-summary recovery loop:
  - ai_summary_started_at  TIMESTAMPTZ NULL  (set when task transitions to running)
  - ai_summary_error       TEXT NULL         (last failure reason, or recovery note)

Pre-existing rows whose ai_summary_status='running' have their started_at
backfilled to now() so the next cron tick does not immediately treat them as
stale. Other rows keep started_at NULL.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "o3d4e5f6a7b8"
down_revision: str | None = "n2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "episodes",
        sa.Column("ai_summary_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "episodes",
        sa.Column("ai_summary_error", sa.Text(), nullable=True),
    )
    op.execute(
        "UPDATE episodes SET ai_summary_started_at = now() "
        "WHERE ai_summary_status = 'running'"
    )


def downgrade() -> None:
    op.drop_column("episodes", "ai_summary_error")
    op.drop_column("episodes", "ai_summary_started_at")
