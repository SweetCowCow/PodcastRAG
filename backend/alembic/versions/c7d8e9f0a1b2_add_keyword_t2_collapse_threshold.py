"""add app_settings.keyword_t2_collapse_threshold

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-05-31

Part of change `keyword-index-mode`. Adds the admin-tunable T1→T2 collapse
threshold to the singleton `app_settings` row. NOT NULL with server_default 10
so the existing id=1 row backfills cleanly without a separate UPDATE.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b6c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "keyword_t2_collapse_threshold",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "keyword_t2_collapse_threshold")
