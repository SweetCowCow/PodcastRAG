"""add transcription_queue.failure_count for consecutive lost-run termination

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-10

Part of change `worker-reliability-and-deeplink-fixes` (D2). Counts how many
times orphan-revert has resurrected a row whose running task was lost; at
MAX_CONSECUTIVE_FAILURES (3) the row is terminated `failed` instead of
re-entering `pending`, breaking the infinite redispatch loop (EP326 incident,
2026-07-10). Additive with server_default so the deploy-time
`alembic upgrade head` is safe on live rows; existing rows start at 0.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcription_queue",
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("transcription_queue", "failure_count")
