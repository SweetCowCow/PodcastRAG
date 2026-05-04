"""add quota_requests table

Revision ID: p4e5f6a7b8c9
Revises: o3d4e5f6a7b8
Create Date: 2026-05-04

Adds the quota_requests table used by the freemium-onboarding change. Each row
records one user's request for additional quota; admin processes via the
admin queue tab; a beat task digests pending rows to admin email twice daily.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "p4e5f6a7b8c9"
down_revision: str | None = "o3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


QUOTA_REQUEST_STATUS_ENUM = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    name="quota_request_status_enum",
    create_type=True,
)


def upgrade() -> None:
    QUOTA_REQUEST_STATUS_ENUM.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "quota_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "approved",
                "rejected",
                name="quota_request_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("granted_amount", sa.Integer(), nullable=True),
        sa.Column("rejection_note", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "processed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_quota_requests_status_last_digest_at",
        "quota_requests",
        ["status", "last_digest_at"],
    )
    op.create_index(
        "ix_quota_requests_user_id_requested_at",
        "quota_requests",
        ["user_id", sa.text("requested_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_quota_requests_user_id_requested_at", table_name="quota_requests")
    op.drop_index("ix_quota_requests_status_last_digest_at", table_name="quota_requests")
    op.drop_table("quota_requests")
    QUOTA_REQUEST_STATUS_ENUM.drop(op.get_bind(), checkfirst=True)
