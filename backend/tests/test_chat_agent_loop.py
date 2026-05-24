"""Tests for chat_agent.agent (chat-agentic-tool-routing change).

Tests cover:
  - Happy-path enumeration: find_episodes_by_topic called + answer non-empty
  - Tool exception caught: run_agent returns (not raises), trace has raised field
  - Iteration cap: agent_truncated=True when loop hits max_iterations
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat_agent.agent import ChatAgentResult, run_agent


def _db_mock() -> MagicMock:
    """AsyncSession-like mock with `begin_nested()` as an async context
    manager (required by `_dispatch_tool` SAVEPOINT wrapper)."""

    @asynccontextmanager
    async def _nested():
        yield None

    db = MagicMock()
    db.begin_nested = _nested
    return db


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


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
) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = (
        [_make_tool_call_obj(tc["id"], tc["name"], tc["args"]) for tc in tool_calls_data]
        if tool_calls_data
        else []
    )
    choice = MagicMock(message=msg)
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    return resp


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def get(self, key: str):
        return self._store.get(key)

    def set(self, key: str, value, ex: int | None = None) -> None:
        if isinstance(value, str):
            value = value.encode()
        self._store[key] = value

    def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_agent_happy_path_enumeration():
    """LLM calls find_episodes_by_topic once, then gives a final answer.

    Spec scenario: "Happy-path enumeration query"
    - THEN the agent SHALL call `find_episodes_by_topic` at least once
    - AND ChatAgentResult.answer SHALL be a non-empty string
    - AND tool_calls SHALL contain at least one entry with name="find_episodes_by_topic"
    - AND agent_truncated SHALL be false
    """
    session_id = uuid.uuid4()
    show_id = uuid.uuid4()
    ep_id = uuid.uuid4()

    tool_response = _make_llm_response(
        content=None,
        tool_calls_data=[
            {"id": "call_01", "name": "find_episodes_by_topic", "args": {"topic": "歌單"}}
        ],
    )
    answer_response = _make_llm_response(content="節目共有 3 集歌單：EP101、EP112、EP120。")

    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(
        side_effect=[tool_response, answer_response]
    )

    from app.schemas.query import EpisodeRef
    from datetime import datetime, timezone

    fake_episodes = [
        EpisodeRef(
            episode_id=ep_id,
            title="歌單 EP101",
            published_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
        EpisodeRef(
            episode_id=uuid.uuid4(),
            title="歌單 EP112",
            published_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        ),
        EpisodeRef(
            episode_id=uuid.uuid4(),
            title="歌單 EP120",
            published_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        ),
    ]

    with (
        patch("app.services.chat_agent.agent.get_step_config", return_value=_fake_step_config()),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client),
        patch("app.services.chat_agent.state._get_redis", return_value=_FakeRedis()),
        patch(
            "app.services.chat_agent.tools.episode_finders.find_episodes_by_topic",
            new_callable=AsyncMock,
            return_value=fake_episodes,
        ),
        patch("app.services.chat_agent.agent._try_update_summary", new_callable=AsyncMock),
    ):
        result = await run_agent("歌單有哪幾集？", session_id, show_id, _db_mock())

    assert isinstance(result, ChatAgentResult)
    assert result.answer == "節目共有 3 集歌單：EP101、EP112、EP120。"
    assert not result.agent_truncated
    tool_names = [tc.name for tc in result.tool_calls]
    assert "find_episodes_by_topic" in tool_names


@pytest.mark.asyncio
async def test_tool_exception_caught_not_5xx():
    """When a tool raises, run_agent returns normally (not raises).

    Spec scenario: "Tool raises exception is caught and converted"
    - THEN agent loop SHALL catch exception, append error JSON as tool-result
    - AND HTTP response SHALL NOT be a 5xx (run_agent doesn't raise)
    - AND tool_calls SHALL contain entry with raised != None
    """
    session_id = uuid.uuid4()
    show_id = uuid.uuid4()

    tool_response = _make_llm_response(
        content=None,
        tool_calls_data=[
            {"id": "call_02", "name": "find_episode_by_ref", "args": {"ref": "EP999"}}
        ],
    )
    answer_response = _make_llm_response(content="查不到 EP999 這集。")

    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(
        side_effect=[tool_response, answer_response]
    )

    with (
        patch("app.services.chat_agent.agent.get_step_config", return_value=_fake_step_config()),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client),
        patch("app.services.chat_agent.state._get_redis", return_value=_FakeRedis()),
        patch(
            "app.services.chat_agent.tools.episode_finders.find_by_ref",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB timeout"),
        ),
        patch("app.services.chat_agent.agent._try_update_summary", new_callable=AsyncMock),
    ):
        result = await run_agent("EP999 的內容？", session_id, show_id, _db_mock())

    assert isinstance(result, ChatAgentResult)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].raised == "RuntimeError"
    # chat-tool-error-isolation: envelope shape replaced the legacy
    # {"error": "..."} dict. Verify the envelope keys land in result_summary.
    assert '"ok": false' in result.tool_calls[0].result_summary
    assert '"kind"' in result.tool_calls[0].result_summary
    assert '"internal_message"' in result.tool_calls[0].result_summary
    assert "RuntimeError" in result.tool_calls[0].result_summary


@pytest.mark.asyncio
async def test_iteration_cap_truncates():
    """LLM keeps emitting tool calls → agent_truncated=True after max_iterations.

    Spec scenario: "Iteration cap reached"
    - THEN ChatAgentResult.agent_truncated SHALL be true
    - AND answer SHALL be the most recent LLM message content
    """
    from app.core.config import settings

    session_id = uuid.uuid4()
    show_id = uuid.uuid4()

    always_tool_response = _make_llm_response(
        content=None,
        tool_calls_data=[
            {"id": "call_loop", "name": "get_show_overview", "args": {}}
        ],
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
            return_value=({"title": "Test Show", "overview": "..."}, None, 5.0),
        ),
        patch("app.services.chat_agent.agent._try_update_summary", new_callable=AsyncMock),
    ):
        result = await run_agent("show overview?", session_id, show_id, _db_mock())

    assert result.agent_truncated is True
    assert len(result.tool_calls) == settings.agentic_chat_max_iterations
