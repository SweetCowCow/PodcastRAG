"""extend show_schedules with refresh tracking and max_episodes_per_run

Revision ID: g5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-04-27

Migrates the existing ``max_episodes`` column (with 0 = unlimited semantics)
to a required ``max_episodes_per_run`` column. Rows with ``max_episodes = 0``
are rewritten to 5 as a sensible default since the unlimited semantic is
removed.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g5b6c7d8e9f0"
down_revision: str | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    refresh_status = sa.Enum("never", "success", "failed", name="refresh_status")
    refresh_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "show_schedules",
        sa.Column(
            "max_episodes_per_run",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
    )
    op.add_column(
        "show_schedules",
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "show_schedules",
        sa.Column(
            "last_refresh_status",
            refresh_status,
            nullable=False,
            server_default=sa.text("'never'"),
        ),
    )
    op.add_column(
        "show_schedules",
        sa.Column("last_refresh_message", sa.String(500), nullable=True),
    )

    op.execute(
        """
        UPDATE show_schedules
        SET max_episodes_per_run = CASE
            WHEN max_episodes = 0 THEN 5
            ELSE max_episodes
        END
        """
    )

    op.alter_column(
        "show_schedules",
        "max_episodes_per_run",
        server_default=None,
    )

    op.drop_column("show_schedules", "max_episodes")


def downgrade() -> None:
    op.add_column(
        "show_schedules",
        sa.Column(
            "max_episodes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.execute(
        "UPDATE show_schedules SET max_episodes = max_episodes_per_run"
    )
    op.alter_column("show_schedules", "max_episodes", server_default=None)

    op.drop_column("show_schedules", "last_refresh_message")
    op.drop_column("show_schedules", "last_refresh_status")
    op.drop_column("show_schedules", "last_refresh_at")
    op.drop_column("show_schedules", "max_episodes_per_run")

    sa.Enum(name="refresh_status").drop(op.get_bind(), checkfirst=True)
