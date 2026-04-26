"""add transcripts.updated_at

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-26

Existing rows will receive the migration execution timestamp as their
`updated_at` value via `server_default=now()`. This is a one-time backfill
and does not represent the true last-modified time of historical rows.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcripts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("transcripts", "updated_at")
