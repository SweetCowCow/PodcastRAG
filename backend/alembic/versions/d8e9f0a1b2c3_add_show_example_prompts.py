"""add show_example_prompts table

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-05-31

Part of change `per-show-mode-example-prompts`. Stores LLM-pre-generated guiding
example questions per show + per query mode (index / semantic / chat), keyed by
(show_id, mode, ordinal). Read by the public GET /shows/{id}/example-prompts as a
cold-start fallback for the trending-queries chip row.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False so op.create_table does NOT auto-create the type from the
# column; we create it explicitly once via MODE_ENUM.create(checkfirst=True).
MODE_ENUM = postgresql.ENUM(
    "index", "semantic", "chat", name="example_prompt_mode_enum", create_type=False
)


def upgrade() -> None:
    MODE_ENUM.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "show_example_prompts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "show_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", MODE_ENUM, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("model", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "show_id", "mode", "ordinal", name="uq_show_example_prompts_show_mode_ordinal"
        ),
    )


def downgrade() -> None:
    op.drop_table("show_example_prompts")
    MODE_ENUM.drop(op.get_bind(), checkfirst=True)
