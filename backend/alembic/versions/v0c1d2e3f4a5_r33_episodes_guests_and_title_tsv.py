"""r3-3 episodes.guests JSONB + episodes.title_tsvector

Revision ID: v0c1d2e3f4a5
Revises: u9b0c1d2e3f4
Create Date: 2026-05-14

R3.3 — Phase 1: metadata-filter & multi-field BM25 foundation.

- ADD COLUMN episodes.guests JSONB NOT NULL DEFAULT '[]'::jsonb
- CREATE INDEX idx_episodes_guests USING GIN (guests jsonb_path_ops)
- ADD COLUMN episodes.title_tsvector tsvector NULL
- CREATE INDEX idx_episodes_title_tsv USING GIN (title_tsvector)

Apply-phase deviation from original task 1.1:
  Task 1.1 specified `title_tsvector` as a GENERATED column using a
  `tokenize_for_tsvector(title)` SQL function. That SQL function does not
  exist in the database — R3.1/R3.2 tokenization runs Python-side via
  jieba (see app/services/description_indexer.py). To keep the new column
  consistent with the existing `transcript_chunks.text_tsvector` and
  `episode_description_chunks.text_tsvector` columns, this migration
  creates a regular nullable column populated Python-side on episode
  insert/update. The downstream BM25 query (Phase 8) is unaffected.

Notes:
- guests column is NOT NULL with `'[]'::jsonb` default. ADD COLUMN with a
  DEFAULT on PG12+ is metadata-only and instant regardless of row count.
- GIN index over empty `[]::jsonb` arrays on ~400 rows is also near-instant;
  CREATE INDEX CONCURRENTLY not required at this scale.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "v0c1d2e3f4a5"
down_revision: str | None = "u9b0c1d2e3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE episodes "
        "ADD COLUMN IF NOT EXISTS guests JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_episodes_guests "
        "ON episodes USING GIN (guests jsonb_path_ops)"
    )

    op.execute(
        "ALTER TABLE episodes "
        "ADD COLUMN IF NOT EXISTS title_tsvector tsvector"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_episodes_title_tsv "
        "ON episodes USING GIN (title_tsvector)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_episodes_title_tsv")
    op.execute("ALTER TABLE episodes DROP COLUMN IF EXISTS title_tsvector")
    op.execute("DROP INDEX IF EXISTS idx_episodes_guests")
    op.execute("ALTER TABLE episodes DROP COLUMN IF EXISTS guests")
