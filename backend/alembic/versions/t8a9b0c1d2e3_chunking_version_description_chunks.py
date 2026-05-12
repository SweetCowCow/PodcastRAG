"""chunking_version + chunk_index on episode_description_chunks

Revision ID: t8a9b0c1d2e3
Revises: s7f8a9b0c1d2
Create Date: 2026-05-12

Enables v1 (legacy whole-description) and v2 (≤200-char chunks) rows to
coexist in `episode_description_chunks`. Adds two smallint columns with
sensible defaults so the existing rows backfill to (1, 0), and swaps the
`(episode_id)` unique constraint for a composite
`(episode_id, chunking_version, chunk_index)` unique.

NOTE: `downgrade()` is only safe BEFORE any v2 row has been written.
Once v2 rows exist, the legacy `(episode_id)` unique would violate. The
operator must run `cleanup_v1_description_chunks.py --execute` (or
manually `DELETE WHERE chunking_version <> 1`) before downgrading.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "t8a9b0c1d2e3"
down_revision: str | None = "s7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "episode_description_chunks",
        sa.Column(
            "chunking_version",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "episode_description_chunks",
        sa.Column(
            "chunk_index",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.drop_constraint(
        "episode_description_chunks_episode_id_key",
        "episode_description_chunks",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_desc_chunk_episode_version_index",
        "episode_description_chunks",
        ["episode_id", "chunking_version", "chunk_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_desc_chunk_episode_version_index",
        "episode_description_chunks",
        type_="unique",
    )
    op.create_unique_constraint(
        "episode_description_chunks_episode_id_key",
        "episode_description_chunks",
        ["episode_id"],
    )
    op.drop_column("episode_description_chunks", "chunk_index")
    op.drop_column("episode_description_chunks", "chunking_version")
