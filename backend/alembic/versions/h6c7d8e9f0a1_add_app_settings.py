"""add app_settings singleton table

Revision ID: h6c7d8e9f0a1
Revises: g5b6c7d8e9f0
Create Date: 2026-04-27

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h6c7d8e9f0a1"
down_revision: str | None = "g5b6c7d8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "max_concurrent_transcriptions",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "monthly_cost_cap_usd",
            sa.Numeric(10, 2),
            nullable=True,
        ),
    )

    op.execute(
        """
        INSERT INTO app_settings (id, max_concurrent_transcriptions, monthly_cost_cap_usd)
        VALUES (1, 1, NULL)
        """
    )


def downgrade() -> None:
    op.drop_table("app_settings")
