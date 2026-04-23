"""add transcription columns

Revision ID: a7b3c9d4e2f1
Revises: 91e48beb1237
Create Date: 2026-04-21

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b3c9d4e2f1"
down_revision: str | None = "91e48beb1237"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "episodes",
        sa.Column("audio_storage_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "transcripts",
        sa.Column("content", sa.Text(), nullable=True),
    )
    op.add_column(
        "transcripts",
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcripts", "error_message")
    op.drop_column("transcripts", "content")
    op.drop_column("episodes", "audio_storage_key")
