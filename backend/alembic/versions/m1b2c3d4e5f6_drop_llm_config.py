"""drop legacy llm_config table (Rev B)

Revision ID: m1b2c3d4e5f6
Revises: l0a1b2c3d4e5
Create Date: 2026-05-03

Run this AFTER deploying the application code that reads ai_steps. Until then,
keep the old table around as a fallback. Downgrade recreates the schema only —
data is not restored.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "m1b2c3d4e5f6"
down_revision: str | None = "l0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("llm_config")


def downgrade() -> None:
    op.create_table(
        "llm_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("answer_base_url", sa.String(500), nullable=False),
        sa.Column("answer_api_key", sa.Text(), nullable=False),
        sa.Column("answer_model", sa.String(200), nullable=False),
        sa.Column("rewrite_base_url", sa.String(500), nullable=False),
        sa.Column("rewrite_api_key", sa.Text(), nullable=False),
        sa.Column("rewrite_model", sa.String(200), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("id = 1", name="ck_llm_config_singleton"),
    )
