"""add eval_traces table for span-level tracing

Revision ID: b6c7d8e9f0a1
Revises: aab5c6d7e8f9
Create Date: 2026-05-29

Part of change `eval-framework-upgrade`.

Span model (OTel-style) for chat agent eval traces. Dual-sink with
Langfuse Cloud (cloud.langfuse.com Free tier) — see design Decision 1a.

Schema follows design Decision 2:
- 4 span identity columns (span_id PK, trace_id, parent_span_id, run_id)
- 3 dataset locator columns (item_id, turn_idx, span_type)
- 3 timing columns (span_name, started_at, ended_at)
- 1 elapsed (elapsed_ms)
- 6 LLM-specific columns (llm_model, llm_finish_reason, llm_prompt_tokens,
  llm_completion_tokens, llm_messages_json, llm_output_text)
- 4 tool-specific columns (tool_name, tool_args_json, tool_result_chunks_json,
  search_query)
- 1 stage column (stage_name)
- 1 meta column (created_at)
= 23 columns total

3 indexes:
- (run_id, item_id) — primary RCA query path
- (trace_id) — Langfuse trace_id ↔ PG join
- (search_query) WHERE search_query IS NOT NULL — prompt fingerprint diff
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: str | None = "aab5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "eval_traces"
IX_RUN_ITEM = "ix_eval_traces_run_item"
IX_TRACE = "ix_eval_traces_trace"
IX_SEARCH_QUERY = "ix_eval_traces_search_query"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        # Span identity
        sa.Column("span_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_span_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        # Dataset locator
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("turn_idx", sa.Integer(), nullable=False),
        sa.Column("span_type", sa.Text(), nullable=False),
        # Timing
        sa.Column("span_name", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        # LLM call fields
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.Column("llm_finish_reason", sa.Text(), nullable=True),
        sa.Column("llm_prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("llm_completion_tokens", sa.Integer(), nullable=True),
        sa.Column("llm_messages_json", postgresql.JSONB(), nullable=True),
        sa.Column("llm_output_text", sa.Text(), nullable=True),
        # Tool call fields
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column("tool_args_json", postgresql.JSONB(), nullable=True),
        sa.Column("tool_result_chunks_json", postgresql.JSONB(), nullable=True),
        sa.Column("search_query", sa.Text(), nullable=True),
        # Stage timing
        sa.Column("stage_name", sa.Text(), nullable=True),
        # Meta
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("span_id", name=f"pk_{TABLE_NAME}"),
        sa.CheckConstraint(
            "span_type IN ('llm_call', 'tool_call', 'stage')",
            name=f"ck_{TABLE_NAME}_span_type",
        ),
    )
    op.create_index(IX_RUN_ITEM, TABLE_NAME, ["run_id", "item_id"])
    op.create_index(IX_TRACE, TABLE_NAME, ["trace_id"])
    op.create_index(
        IX_SEARCH_QUERY,
        TABLE_NAME,
        ["search_query"],
        postgresql_where=sa.text("search_query IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(IX_SEARCH_QUERY, table_name=TABLE_NAME)
    op.drop_index(IX_TRACE, table_name=TABLE_NAME)
    op.drop_index(IX_RUN_ITEM, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
