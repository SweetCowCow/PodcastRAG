"""Dual-sink span writer: PG `eval_traces` table + Langfuse Cloud SDK.

Part of change `eval-framework-upgrade` (2026-05-29). See design Decision 1a
(雙寫 vs Cloud single source of truth) and Decision 7 (fail-safe).

Dual-sink layout:
- **PG sink**: synchronous INSERT into `eval_traces` via SQLAlchemy AsyncSession.
  Authoritative for long-term audit, SQL-based RCA, and MCP query integration.
  Survives Langfuse Cloud Free 30-day retention expiry.
- **Langfuse Cloud sink**: handled by the `@observe` decorator at call sites.
  The Langfuse SDK auto-batches and uploads spans in a background thread.
  This writer does NOT call Langfuse SDK directly — instrumentation is done
  at the `@observe`-decorated function boundary, not here.

Failure handling (per Decision 7): every PG insert is wrapped in try/except.
On failure, log a warning and return — never raise to the caller. The chat
agent loop and eval runner MUST NOT block on span persistence.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.core.database import AsyncSessionFactory

logger = logging.getLogger(__name__)


# Column allowlist guards against typos and accidental injection of unknown
# keys (span_dict comes from instrumentation code; we treat it as semi-trusted).
_ALLOWED_COLUMNS: frozenset[str] = frozenset(
    {
        # span identity
        "span_id",
        "trace_id",
        "parent_span_id",
        "run_id",
        # dataset locator
        "item_id",
        "turn_idx",
        "span_type",
        # timing
        "span_name",
        "started_at",
        "ended_at",
        "elapsed_ms",
        # LLM call fields
        "llm_model",
        "llm_finish_reason",
        "llm_prompt_tokens",
        "llm_completion_tokens",
        "llm_messages_json",
        "llm_output_text",
        # tool call fields
        "tool_name",
        "tool_args_json",
        "tool_result_chunks_json",
        "search_query",
        # stage
        "stage_name",
    }
)

_REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "span_id",
        "trace_id",
        "run_id",
        "item_id",
        "turn_idx",
        "span_type",
        "span_name",
        "started_at",
    }
)

_VALID_SPAN_TYPES: frozenset[str] = frozenset({"llm_call", "tool_call", "stage"})


async def write_span(span_dict: dict[str, Any]) -> None:
    """Insert a single span row into `eval_traces`. Fire-and-forget.

    `span_dict` keys are filtered against `_ALLOWED_COLUMNS`. UUID-typed
    fields accept either `uuid.UUID` instances or string representations.

    NEVER raises — failures are logged at WARNING level. Caller (chat agent
    loop, eval runner) MUST treat this as best-effort.
    """
    # Validate required keys before opening a session (cheap fast-path).
    missing = _REQUIRED_COLUMNS - span_dict.keys()
    if missing:
        logger.warning("eval_traces: skipping span; missing required keys: %s", missing)
        return

    span_type = span_dict.get("span_type")
    if span_type not in _VALID_SPAN_TYPES:
        logger.warning(
            "eval_traces: skipping span; invalid span_type=%r (allowed: %s)",
            span_type,
            sorted(_VALID_SPAN_TYPES),
        )
        return

    # Filter to allowed columns; drop unknown keys silently.
    filtered = {k: v for k, v in span_dict.items() if k in _ALLOWED_COLUMNS}
    # Normalize UUID-typed fields to UUID objects (asyncpg + sqlalchemy expect this).
    for uuid_field in ("span_id", "trace_id", "parent_span_id"):
        v = filtered.get(uuid_field)
        if v is not None and not isinstance(v, UUID):
            try:
                filtered[uuid_field] = UUID(str(v))
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "eval_traces: skipping span; invalid UUID for %s=%r (%s)",
                    uuid_field,
                    v,
                    exc,
                )
                return

    columns = list(filtered.keys())
    placeholders = ", ".join(f":{c}" for c in columns)
    column_list = ", ".join(columns)
    sql = text(
        f"INSERT INTO eval_traces ({column_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (span_id) DO NOTHING"
    )

    try:
        async with AsyncSessionFactory() as session:
            await session.execute(sql, filtered)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        # Per Decision 7: never raise; trace persistence is best-effort.
        logger.warning(
            "eval_traces: insert failed for span_id=%s (%s)",
            filtered.get("span_id"),
            exc,
        )
