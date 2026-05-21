"""Tests for agent-trace-telemetry change.

Verifies `run_agent` populates `ChatAgentResult.llm_calls` + `stage_timings`
across happy-path, truncate, and fail-open code paths. Mocks mirror the
existing chat_agent test conventions in `test_chat_agent_loop.py`.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat_agent.agent import (
    ChatAgentResult,
    LLMCallTrace,
    StageTimings,
    run_agent,
)


def _db_mock() -> MagicMock:
    """AsyncSession-like mock with `begin_nested()` as an async context manager."""

    @asynccontextmanager
    async def _nested():
        yield None

    db = MagicMock()
    db.begin_nested = _nested
    return db


def _fake_step_config(model: str = "gpt-4o") -> MagicMock:
    cfg = MagicMock()
    cfg.base_url = "https://fake.endpoint/v1"
    cfg.api_key = "sk-fake"
    cfg.model = model
    return cfg


def _make_tool_call_obj(call_id: str, name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _make_llm_response(
    content: str | None,
    tool_calls_data: list[dict] | None = None,
    finish_reason: str = "stop",
) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = (
        [_make_tool_call_obj(tc["id"], tc["name"], tc["args"]) for tc in tool_calls_data]
        if tool_calls_data
        else []
    )
    choice = MagicMock(message=msg, finish_reason=finish_reason)
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    return resp


class _FakeRedis:
    def __init__(self, raise_on_save: bool = False) -> None:
        self._store: dict[str, bytes] = {}
        self._raise_on_save = raise_on_save

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value, ex: int | None = None) -> None:
        if self._raise_on_save:
            raise RuntimeError("redis down")
        if isinstance(value, str):
            value = value.encode()
        self._store[key] = value

    def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0


@pytest.mark.asyncio
async def test_telemetry_populated_on_success():
    """Spec: Trace populated on successful chat turn.

    Two LLM rounds (1 tool round + 1 final answer) → llm_calls has 2 entries
    with non-negative latency_ms and non-empty finish_reason.
    """
    session_id = uuid.uuid4()
    show_id = uuid.uuid4()

    tool_response = _make_llm_response(
        content=None,
        tool_calls_data=[
            {"id": "call_01", "name": "get_show_overview", "args": {}}
        ],
        finish_reason="tool_calls",
    )
    answer_response = _make_llm_response(content="節目摘要…", finish_reason="stop")

    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(
        side_effect=[tool_response, answer_response]
    )

    with (
        patch("app.services.chat_agent.agent.get_step_config", return_value=_fake_step_config()),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client),
        patch("app.services.chat_agent.state._get_redis", return_value=_FakeRedis()),
        patch(
            "app.services.chat_agent.agent._dispatch_tool",
            new_callable=AsyncMock,
            return_value=({"title": "T", "overview": "O"}, None, 5.0),
        ),
        patch("app.services.chat_agent.agent._try_update_summary", new_callable=AsyncMock),
    ):
        result = await run_agent("節目簡介？", session_id, show_id, _db_mock())

    assert isinstance(result, ChatAgentResult)
    # Two LLM rounds: one with tool_calls, one terminal answer.
    assert len(result.llm_calls) == 2
    assert all(isinstance(lc, LLMCallTrace) for lc in result.llm_calls)
    assert all(lc.latency_ms >= 0 for lc in result.llm_calls)
    assert all(lc.finish_reason for lc in result.llm_calls)
    assert result.llm_calls[0].had_tool_calls is True
    assert result.llm_calls[1].had_tool_calls is False
    assert result.llm_calls[0].round_index == 0
    assert result.llm_calls[1].round_index == 1

    # tool_calls retain existing fields + new result_full populated.
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].latency_ms == 5.0
    assert result.tool_calls[0].result_summary  # non-empty
    assert result.tool_calls[0].result_full is not None

    # stage_timings populated.
    assert isinstance(result.stage_timings, StageTimings)
    assert result.stage_timings.llm_loop_total_ms > 0
    assert result.stage_timings.build_messages_ms >= 0
    assert result.stage_timings.state_load_ms >= 0
    assert result.stage_timings.state_save_ms >= 0
    assert result.stage_timings.history_summary_ms >= 0


@pytest.mark.asyncio
async def test_telemetry_on_truncate():
    """Spec: Trace populated on agent-truncated turn.

    LLM never emits terminal answer → loop exits via truncate path. llm_calls
    SHALL contain exactly `agentic_chat_max_iterations` entries.
    """
    from app.core.config import settings

    session_id = uuid.uuid4()
    show_id = uuid.uuid4()

    always_tool_response = _make_llm_response(
        content=None,
        tool_calls_data=[
            {"id": "call_loop", "name": "get_show_overview", "args": {}}
        ],
        finish_reason="tool_calls",
    )

    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(return_value=always_tool_response)

    with (
        patch("app.services.chat_agent.agent.get_step_config", return_value=_fake_step_config()),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client),
        patch("app.services.chat_agent.state._get_redis", return_value=_FakeRedis()),
        patch(
            "app.services.chat_agent.agent._dispatch_tool",
            new_callable=AsyncMock,
            return_value=({"title": "T", "overview": "O"}, None, 5.0),
        ),
        patch("app.services.chat_agent.agent._try_update_summary", new_callable=AsyncMock),
    ):
        result = await run_agent("loop forever", session_id, show_id, _db_mock())

    assert result.agent_truncated is True
    assert len(result.llm_calls) == settings.agentic_chat_max_iterations
    assert result.stage_timings.llm_loop_total_ms > 0


@pytest.mark.asyncio
async def test_telemetry_stage_save_failopen():
    """Spec: Stage timing for fail-open path.

    state_store.save raises → existing fail-open catch swallows the exception,
    chat response NOT 5xx, but stage_timings.state_save_ms still records the
    elapsed-ms of the failed attempt.
    """
    session_id = uuid.uuid4()
    show_id = uuid.uuid4()

    answer_response = _make_llm_response(content="ok", finish_reason="stop")
    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(return_value=answer_response)

    with (
        patch("app.services.chat_agent.agent.get_step_config", return_value=_fake_step_config()),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client),
        patch(
            "app.services.chat_agent.state._get_redis",
            return_value=_FakeRedis(raise_on_save=True),
        ),
        patch("app.services.chat_agent.agent._try_update_summary", new_callable=AsyncMock),
    ):
        # MUST NOT raise — fail-open path.
        result = await run_agent("q", session_id, show_id, _db_mock())

    assert result.answer == "ok"
    assert result.stage_timings.state_save_ms >= 0  # recorded despite failure
