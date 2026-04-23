"""add_rag_tables

Revision ID: c1f2d3e4a5b6
Revises: a7b3c9d4e2f1
Create Date: 2026-04-23

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c1f2d3e4a5b6"
down_revision: str | None = "a7b3c9d4e2f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcript_chunks",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "transcript_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("transcripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("start_time", sa.Float, nullable=False),
        sa.Column("end_time", sa.Float, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "segment_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "transcript_id", "chunk_index", name="uq_chunk_transcript_index"
        ),
    )
    op.create_index(
        "ix_chunks_transcript",
        "transcript_chunks",
        ["transcript_id"],
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding ON transcript_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "llm_config",
        sa.Column(
            "id",
            sa.Integer,
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("answer_base_url", sa.String(500), nullable=False),
        sa.Column("answer_api_key", sa.Text, nullable=False),
        sa.Column("answer_model", sa.String(200), nullable=False),
        sa.Column("rewrite_base_url", sa.String(500), nullable=False),
        sa.Column("rewrite_api_key", sa.Text, nullable=False),
        sa.Column("rewrite_model", sa.String(200), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_llm_config_singleton"),
    )

    op.execute(
        "INSERT INTO llm_config "
        "(id, answer_base_url, answer_api_key, answer_model, "
        "rewrite_base_url, rewrite_api_key, rewrite_model) "
        "VALUES (1, 'https://hnd1.aihub.zeabur.ai/v1', '', 'gpt-4o', "
        "'https://hnd1.aihub.zeabur.ai/v1', '', 'gpt-4o-mini')"
    )

    op.drop_column("transcript_segments", "embedding")


def downgrade() -> None:
    op.add_column(
        "transcript_segments",
        sa.Column("embedding", Vector(1536), nullable=True),
    )

    op.drop_table("llm_config")

    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding")
    op.drop_index("ix_chunks_transcript", table_name="transcript_chunks")
    op.drop_table("transcript_chunks")
