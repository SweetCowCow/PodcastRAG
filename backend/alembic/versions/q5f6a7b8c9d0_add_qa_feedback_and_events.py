"""add qa_feedback and events tables

Revision ID: q5f6a7b8c9d0
Revises: p4e5f6a7b8c9
Create Date: 2026-05-05

R1.1 — UI feedback infra. Adds two append-only tables:
- qa_feedback: thumbs up/down + optional comment per AI answer (login required).
- events: generic client event log; v1 only ingests citation_click rows
  (anonymous + logged-in).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "q5f6a7b8c9d0"
down_revision: str | None = "p4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "qa_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("query_id", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vote", sa.String(length=8), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("vote IN ('up', 'down')", name="ck_qa_feedback_vote"),
    )
    op.create_index(
        "ix_qa_feedback_query_user_created",
        "qa_feedback",
        ["query_id", "user_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("event_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_events_type_created",
        "events",
        ["event_type", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_events_type_created", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_qa_feedback_query_user_created", table_name="qa_feedback")
    op.drop_table("qa_feedback")
