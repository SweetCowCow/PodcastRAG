"""add day_of_week to show_schedules

Revision ID: j8e9f0a1b2c3
Revises: i7d8e9f0a1b2
Create Date: 2026-04-30

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j8e9f0a1b2c3"
down_revision: str | None = "i7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "show_schedules",
        sa.Column(
            "day_of_week",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("show_schedules", "day_of_week")
