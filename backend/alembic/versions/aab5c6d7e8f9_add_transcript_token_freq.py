"""add transcript_token_freq table for IDF cache

Revision ID: aab5c6d7e8f9
Revises: a5b6c7d8e9f0
Create Date: 2026-05-28

Part of change `retrieve-quality-step1-idf-and-prefilter` (Layer A, REVERTED).

NOTE: The application code that used this table (lexical_idf.py +
admin_lexical_idf.py + rag.py bucketed SQL) was reverted on 2026-05-28
after the chat eval baseline regressed (chunk_recall 0.482 → 0.382,
factual_correctness 0.892 → 0.831). See case study
`docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-28.md`.

The migration is kept (rather than down-migrated) because:
1. Prod already ran the upgrade — alembic_version is at `aab5c6d7e8f9`.
2. Dropping the file would force a manual rollback of `alembic_version`.
3. The orphan table is harmless (no code references it) and < 100MB.
4. A future change may reuse this table if a different IDF design ships.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "aab5c6d7e8f9"
down_revision: str | None = "a5b6c7d8e9f0"
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
