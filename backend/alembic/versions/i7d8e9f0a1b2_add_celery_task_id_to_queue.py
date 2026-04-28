"""add celery_task_id to transcription_queue

Revision ID: i7d8e9f0a1b2
Revises: h6c7d8e9f0a1
Create Date: 2026-04-28

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i7d8e9f0a1b2"
down_revision: str | None = "h6c7d8e9f0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcription_queue",
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transcription_queue", "celery_task_id")
