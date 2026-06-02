"""add original_text/original_content for ASR correction reversibility

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-02

Part of change `asr-correction-reversibility-and-content-sync` (EQ2d). Adds the
pre-correction snapshots that make ASR corrections reversible:

- `transcript_segments.original_text` (nullable text)
- `transcripts.original_content` (nullable text)

Both default NULL and existing rows are NOT backfilled — episodes corrected
before this change have no preserved original (a deliberate Non-Goal; they are
handled by re-transcription, and their content is brought into display
consistency by the forced content re-sync in backfill).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcript_segments",
        sa.Column("original_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "transcripts",
        sa.Column("original_content", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcripts", "original_content")
    op.drop_column("transcript_segments", "original_text")
