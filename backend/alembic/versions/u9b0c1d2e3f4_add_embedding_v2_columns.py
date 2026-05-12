"""r3-4 add embedding_v2 columns + HNSW indexes

Revision ID: u9b0c1d2e3f4
Revises: t8a9b0c1d2e3
Create Date: 2026-05-12

R3.4 — Blue-Green embedding-model swap (text-embedding-3-small -> -large).

- ADD COLUMN transcript_chunks.embedding_v2 vector(3072) NULL
- ADD COLUMN episode_description_chunks.embedding_v2 vector(3072) NULL
- CREATE INDEX CONCURRENTLY ... USING hnsw on a halfvec(3072) cast (pgvector
  vector_cosine_ops HNSW maxDim is 2000; halfvec_cosine_ops supports up to
  4000, ample for 3072). Read-side SQL must cosine-compare via the same
  halfvec cast for the index to be used.

Notes:
- This migration only adds nullable columns + indexes. NO embedding values
  are written here. Backfill is a separate operational script
  (`backend/scripts/backfill_embedding_v2.py`) so we can rate-limit and
  resume.
- The `ai_steps` row stays on `text-embedding-3-small` until cutover (admin
  UI flip) — see r3-4 design D2 + Open Question 1.
- CREATE INDEX CONCURRENTLY must run OUTSIDE a transaction. Alembic by
  default wraps each migration in a transaction; we force autocommit per
  Alembic docs (`with op.get_context().autocommit_block()`).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "u9b0c1d2e3f4"
down_revision: str | None = "t8a9b0c1d2e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) Add columns (transactional).
    op.execute(
        "ALTER TABLE transcript_chunks "
        "ADD COLUMN IF NOT EXISTS embedding_v2 vector(3072)"
    )
    op.execute(
        "ALTER TABLE episode_description_chunks "
        "ADD COLUMN IF NOT EXISTS embedding_v2 vector(3072)"
    )

    # 2) HNSW indexes via halfvec cast (vector_cosine_ops HNSW maxDim=2000;
    #    halfvec_cosine_ops supports up to 4000).
    #
    #    Note: We deliberately do NOT use CREATE INDEX CONCURRENTLY here.
    #    The async alembic env (`run_sync` over a single async connection)
    #    doesn't play cleanly with `autocommit_block`. Building HNSW over
    #    an empty column is near-instant; the populating backfill happens
    #    in a separate script after migration apply.
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_transcript_chunks_emb_v2_hnsw "
        "ON transcript_chunks "
        "USING hnsw ((embedding_v2::halfvec(3072)) halfvec_cosine_ops) "
        "WITH (m=16, ef_construction=64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "idx_desc_chunks_emb_v2_hnsw "
        "ON episode_description_chunks "
        "USING hnsw ((embedding_v2::halfvec(3072)) halfvec_cosine_ops) "
        "WITH (m=16, ef_construction=64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_desc_chunks_emb_v2_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_transcript_chunks_emb_v2_hnsw")
    op.execute(
        "ALTER TABLE episode_description_chunks DROP COLUMN IF EXISTS embedding_v2"
    )
    op.execute(
        "ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS embedding_v2"
    )
