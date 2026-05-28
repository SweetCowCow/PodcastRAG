"""add transcript_token_freq table for IDF cache

Revision ID: aab5c6d7e8f9
Revises: z4a5b6c7d8e9
Create Date: 2026-05-28

Part of change `retrieve-quality-step1-idf-and-prefilter` (Layer A).

Stores per-show token document frequency + IDF for lexical retrieval
weighting. Populated by `lexical_idf.refresh_freq_table()`, consumed by
`lexical_idf.get_idf_weights()` to map query tokens to ts_rank_cd
weight categories (A/B/C/D).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "aab5c6d7e8f9"
down_revision: str | None = "z4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "transcript_token_freq"
INDEX_NAME = "ix_transcript_token_freq_show_id"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("show_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("df", sa.BigInteger(), nullable=False),
        sa.Column("total_docs", sa.BigInteger(), nullable=False),
        sa.Column("idf", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("show_id", "token", name=f"pk_{TABLE_NAME}"),
    )
    op.create_index(INDEX_NAME, TABLE_NAME, ["show_id"])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
