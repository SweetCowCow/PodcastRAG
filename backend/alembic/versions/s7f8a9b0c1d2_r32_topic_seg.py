"""r3.2 topic seg + two-layer retrieval schema

Revision ID: s7f8a9b0c1d2
Revises: r6e7f8a9b0c1
Create Date: 2026-05-08

R3.2 — topic segmentation + two-layer retrieval + tokenizer show-name flag.

- transcript_segments.topic_label (LLM-classified label)
- shows.segment_categories (per-show extension labels)
- tokenizer_custom_terms.is_show_name (exclude from lexical query)
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "s7f8a9b0c1d2"
down_revision: str | None = "r6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcript_segments",
        sa.Column("topic_label", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_segments_topic_label",
        "transcript_segments",
        ["topic_label"],
    )

    op.add_column(
        "shows",
        sa.Column(
            "segment_categories",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.add_column(
        "tokenizer_custom_terms",
        sa.Column(
            "is_show_name",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tokenizer_custom_terms", "is_show_name")
    op.drop_column("shows", "segment_categories")
    op.drop_index("ix_segments_topic_label", table_name="transcript_segments")
    op.drop_column("transcript_segments", "topic_label")
