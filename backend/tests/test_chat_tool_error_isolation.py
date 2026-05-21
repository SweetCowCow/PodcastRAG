"""Tests for chat-tool-error-isolation change.

Covers three requirements:
  - _get_episode_segments SQL uses real columns (start_time / end_time)
  - _dispatch_tool wraps tool callable in SAVEPOINT + returns structured envelope
  - System prompt instructs LLM to use user_hint and not expose internal details

All tests use mocks — no real PG, no docker dependency.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from sqlalchemy.exc import ProgrammingError

from app.services.chat_agent.tools import (
    _classify_exception,
    _dispatch_tool,
    _EPISODE_SEGMENTS_SQL,
    _make_envelope,
    ToolContext,
    ToolSpec,
    TOOLS_BY_NAME,
)
from app.services.chat_agent.state import ChatSessionState


# ──────────────────────────────────────────────────────────────────────
# Helpers — build a ToolContext with a mock AsyncSession whose
# `begin_nested()` is a real async context manager so the production
# `async with ctx.db.begin_nested():` block works without a real PG.
# ──────────────────────────────────────────────────────────────────────


def _make_ctx(begin_nested_raises: BaseException | None = None) -> ToolContext:
    db = MagicMock()
    if begin_nested_raises is None:

        @asynccontextmanager
        async def _begin_nested():
            yield None

        db.begin_nested = _begin_nested
    else:

        @asynccontextmanager
        async def _begin_nested():
            raise begin_nested_raises
            yield None  # pragma: no cover

        db.begin_nested = _begin_nested

    state = ChatSessionState(session_id=uuid.uuid4())
    state_store = MagicMock()
    state_store.save = MagicMock()
    return ToolContext(db=db, show_id=uuid.uuid4(), state=state, state_store=state_store)


class _DummyInput(BaseModel):
    query: str = ""


def _register_dummy_tool(name: str, callable_):
    """Inject a fake tool into TOOLS_BY_NAME for a single test."""
    spec = ToolSpec(
        name=name,
        input_model=_DummyInput,
        callable=callable_,
        description="test fake",
    )
    TOOLS_BY_NAME[name] = spec
    return spec


def _unregister_dummy_tool(name: str):
    TOOLS_BY_NAME.pop(name, None)


# ──────────────────────────────────────────────────────────────────────
# Section 1: SQL column references
# ──────────────────────────────────────────────────────────────────────


def test_sql_uses_real_columns():
    """_EPISODE_SEGMENTS_SQL must select start_time/end_time, not the
    non-existent start_seconds/end_seconds columns.

    Spec scenario: '_get_episode_segments succeeds on prod schema'
    (SQL prerequisite).
    """
    assert "ts.start_time" in _EPISODE_SEGMENTS_SQL
    assert "ts.end_time" in _EPISODE_SEGMENTS_SQL
    assert "ts.start_seconds" not in _EPISODE_SEGMENTS_SQL
    assert "ts.end_seconds" not in _EPISODE_SEGMENTS_SQL
    # ORDER BY must also use the real column
    assert "ORDER BY ts.start_time" in _EPISODE_SEGMENTS_SQL


# ──────────────────────────────────────────────────────────────────────
# Section 2: SAVEPOINT isolation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_savepoint_isolation_first_tool_raises_second_runs():
    """Spec scenario: 'Tool raises ProgrammingError, next tool still works'.

    First tool callable raises ProgrammingError. SAVEPOINT rolls back.
    Second tool callable then runs successfully on the same ctx.db.
    Verifies the dispatcher does not call outer db.rollback() (that
    would discard the chat_session L1 state). Envelope shape verified
    on the first call.
    """
    ctx = _make_ctx()
    # Track whether outer rollback was invoked
    ctx.db.rollback = AsyncMock()

    async def _raise_pg(inp, ctx):
        raise ProgrammingError("SELECT bad", {}, Exception("column does not exist"))

    async def _ok(inp, ctx):
        return {"result": "next tool worked"}

    _register_dummy_tool("dummy_raise", _raise_pg)
    _register_dummy_tool("dummy_ok", _ok)
    try:
        env1, raised1, _ = await _dispatch_tool("dummy_raise", {"query": "x"}, ctx)
        env2, raised2, _ = await _dispatch_tool("dummy_ok", {"query": "x"}, ctx)
    finally:
        _unregister_dummy_tool("dummy_raise")
        _unregister_dummy_tool("dummy_ok")

    # First tool: envelope kind=schema, raised=ProgrammingError
    assert env1["ok"] is False
    assert env1["kind"] == "schema"
    assert "ProgrammingError" in env1["internal_message"]
    assert raised1 == "ProgrammingError"

    # Second tool: succeeded (not an envelope, raised=None)
    assert env2 == {"result": "next tool worked"}
    assert raised2 is None

    # Outer rollback MUST NOT have been called (SAVEPOINT handles
    # rollback; outer session keeps its other pending state intact).
    ctx.db.rollback.assert_not_called()


# ──────────────────────────────────────────────────────────────────────
# Section 3: Envelope kinds + user_hint sanitisation
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_envelope_validation_kind():
    """Spec scenario: 'Validation error classified'.

    Tool invoked with args that fail Pydantic validation → kind=validation,
    internal_message contains 'ValidationError', user_hint does not.
    """
    ctx = _make_ctx()

    class _StrictInput(BaseModel):
        required_field: str

    async def _never_called(inp, ctx):  # pragma: no cover
        raise AssertionError("should not be called")

    spec = ToolSpec(
        name="dummy_strict",
        input_model=_StrictInput,
        callable=_never_called,
        description="t",
    )
    TOOLS_BY_NAME["dummy_strict"] = spec
    try:
        env, raised, _ = await _dispatch_tool("dummy_strict", {"wrong": "arg"}, ctx)
    finally:
        _unregister_dummy_tool("dummy_strict")

    assert env["ok"] is False
    assert env["kind"] == "validation"
    assert env["internal_message"].startswith("ValidationError")
    assert "ValidationError" not in env["user_hint"]
    assert raised == "ValidationError"


@pytest.mark.asyncio
async def test_envelope_schema_kind_user_hint_sanitised():
    """Spec scenario: 'Schema error classified and user_hint sanitised'.

    ProgrammingError → kind=schema, internal_message contains class name +
    column reference; user_hint contains none of 'ProgrammingError',
    'start_seconds', or 'transaction'.
    """
    ctx = _make_ctx()

    async def _raise_schema(inp, ctx):
        raise ProgrammingError("SELECT bad", {}, Exception("column ts.start_seconds does not exist"))

    _register_dummy_tool("dummy_schema", _raise_schema)
    try:
        env, raised, _ = await _dispatch_tool("dummy_schema", {"query": "x"}, ctx)
    finally:
        _unregister_dummy_tool("dummy_schema")

    assert env["kind"] == "schema"
    assert "ProgrammingError" in env["internal_message"]
    assert "start_seconds" in env["internal_message"]
    hint = env["user_hint"]
    assert "ProgrammingError" not in hint
    assert "start_seconds" not in hint
    assert "transaction" not in hint
    assert raised == "ProgrammingError"


def test_envelope_transient_kind_timeout():
    """asyncio.TimeoutError → kind=transient, zh-TW user_hint."""
    env = _make_envelope(asyncio.TimeoutError())
    assert env["ok"] is False
    assert env["kind"] == "transient"
    # zh-TW phrasing — contains CJK characters
    assert any("一" <= ch <= "鿿" for ch in env["user_hint"])


def test_envelope_unknown_kind_runtime_error():
    """Spec scenario: 'Unknown exception falls back gracefully'.

    Exception type outside the classifier dispatch table → kind=unknown,
    zh-TW user_hint.
    """
    env = _make_envelope(RuntimeError("something weird"))
    assert env["kind"] == "unknown"
    assert "RuntimeError" in env["internal_message"]
    assert any("一" <= ch <= "鿿" for ch in env["user_hint"])


def test_classify_exception_dispatch_table():
    """Direct coverage of the dispatch table for every kind."""
    from pydantic import ValidationError as PydanticVE
    from sqlalchemy.exc import IntegrityError, DataError, OperationalError

    # validation
    try:
        _DummyInput.model_validate({"query": 123, "extra_required": object()})
    except Exception as ve:  # Pydantic raises ValidationError
        kind, _ = _classify_exception(ve)
    # Build a fresh ValidationError via model_validate
    try:

        class _NeedsField(BaseModel):
            x: int

        _NeedsField.model_validate({})
    except PydanticVE as ve:
        assert _classify_exception(ve)[0] == "validation"

    # schema family
    for exc_cls in (ProgrammingError, IntegrityError, DataError):
        assert _classify_exception(exc_cls("stmt", {}, Exception("e")))[0] == "schema"

    # transient: OperationalError + TimeoutError
    assert _classify_exception(OperationalError("stmt", {}, Exception("e")))[0] == "transient"
    assert _classify_exception(asyncio.TimeoutError())[0] == "transient"

    # not_found
    assert _classify_exception(LookupError("not here"))[0] == "not_found"

    # unknown fallback
    assert _classify_exception(RuntimeError("weird"))[0] == "unknown"


# ──────────────────────────────────────────────────────────────────────
# Section 4: System prompt rule
# ──────────────────────────────────────────────────────────────────────


def test_system_prompt_contains_error_handling_rule():
    """Spec scenario: 'Tool result with ok: false produces user-friendly answer'
    (system prompt prerequisite).

    SYSTEM_PROMPT must instruct the LLM to use user_hint and forbid leaking
    internal_message / exception class names / '技術問題'-style phrasings.
    """
    from app.services.chat_agent.prompts import SYSTEM_PROMPT

    assert "Tool 錯誤處理規則" in SYSTEM_PROMPT
    assert "user_hint" in SYSTEM_PROMPT
    assert "禁止" in SYSTEM_PROMPT
    assert "internal_message" in SYSTEM_PROMPT
    # The forbidden phrasings the LLM must not use
    assert "技術問題" in SYSTEM_PROMPT
    assert "ProgrammingError" in SYSTEM_PROMPT  # exemplified as a forbidden class
