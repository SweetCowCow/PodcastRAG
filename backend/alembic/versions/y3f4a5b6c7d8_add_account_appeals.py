"""add account_appeals table

Revision ID: y3f4a5b6c7d8
Revises: x2e3f4a5b6c7
Create Date: 2026-05-18

Adds the account_appeals table used by the disabled-user-appeal-flow change.
Each row records one appeal submission from a disabled user. The
``POST /auth/appeal`` endpoint inserts rows (silent-drop for unknown/active
emails); the ``appeal_digest`` beat task emails admins daily and stamps
``notified_at``.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "y3f4a5b6c7d8"
down_revision: str | None = "x2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_appeals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("client_ip", sa.Text(), nullable=True),
        sa.Column(
            "user_disabled_at_snapshot",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_account_appeals_created_at",
        "account_appeals",
        ["created_at"],
    )
    op.create_index(
        "ix_account_appeals_email",
        "account_appeals",
        ["email"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_appeals_email", table_name="account_appeals")
    op.drop_index("ix_account_appeals_created_at", table_name="account_appeals")
    op.drop_table("account_appeals")
