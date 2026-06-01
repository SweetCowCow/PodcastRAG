"""add asr_correction_terms table

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-06-01

Part of change `asr-correction-dictionary` (EQ2a). Stores deterministic ASR typo
correction rules (wrong→correct), scoped global or per-show. Applied at
transcription time (before chunking) and via admin-triggered backfill.

Uniqueness is enforced with two partial unique indexes rather than a plain
composite UNIQUE(wrong, scope, show_id): Postgres treats NULLs as distinct, so a
composite constraint would not prevent duplicate global rules (show_id NULL).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asr_correction_terms",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("wrong", sa.Text(), nullable=False),
        sa.Column("correct", sa.Text(), nullable=False),
        sa.Column(
            "scope", sa.String(length=10), nullable=False, server_default="show"
        ),
        sa.Column(
            "show_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shows.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # Partial unique indexes — see module docstring for the NULL-distinct rationale.
    op.create_index(
        "uq_asr_correction_global_wrong",
        "asr_correction_terms",
        ["wrong"],
        unique=True,
        postgresql_where=sa.text("scope = 'global'"),
    )
    op.create_index(
        "uq_asr_correction_show_wrong",
        "asr_correction_terms",
        ["wrong", "show_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'show'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_asr_correction_show_wrong", table_name="asr_correction_terms"
    )
    op.drop_index(
        "uq_asr_correction_global_wrong", table_name="asr_correction_terms"
    )
    op.drop_table("asr_correction_terms")
