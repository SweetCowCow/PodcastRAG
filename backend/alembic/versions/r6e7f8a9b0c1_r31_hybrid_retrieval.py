"""r3.1 hybrid retrieval

Revision ID: r6e7f8a9b0c1
Revises: q5f6a7b8c9d0
Create Date: 2026-05-08

R3.1 — Hybrid retrieval (pgvector + tsvector RRF).

- transcript_chunks.text_tsvector + GIN index (populated app-side via jieba)
- tokenizer_custom_terms: admin-curated jieba dictionary
- episode_description_chunks: one row per episode for cleaned RSS description
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "r6e7f8a9b0c1"
down_revision: str | None = "q5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcript_chunks",
        sa.Column("text_tsvector", postgresql.TSVECTOR(), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_chunks_text_tsvector ON transcript_chunks "
        "USING GIN (text_tsvector)"
    )

    op.create_table(
        "tokenizer_custom_terms",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("term", sa.String(length=100), nullable=False, unique=True),
        sa.Column(
            "weight", sa.Integer, nullable=False, server_default=sa.text("100")
        ),
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "episode_description_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("text_tsvector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        "CREATE INDEX ix_desc_text_tsvector ON episode_description_chunks "
        "USING GIN (text_tsvector)"
    )
    op.execute(
        "CREATE INDEX ix_desc_embedding ON episode_description_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_desc_embedding")
    op.execute("DROP INDEX IF EXISTS ix_desc_text_tsvector")
    op.drop_table("episode_description_chunks")
    op.drop_table("tokenizer_custom_terms")
    op.execute("DROP INDEX IF EXISTS ix_chunks_text_tsvector")
    op.drop_column("transcript_chunks", "text_tsvector")
