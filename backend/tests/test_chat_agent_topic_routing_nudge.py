"""Tests for b22-cross-episode-topic-routing.

Covers:
  - Detector `should_force_topic_prefilter`: b23-style cross-episode topical
    question → True; EP-ref / deictic question → False; single discriminating
    token → False; empty → False.
  - `run_agent` first-round `tool_choice`: detector hit + flag on → forced
    `search_with_topic_prefilter` on round 0, "auto" on round 1; detector hit +
    flag off → "auto"; detector miss → "auto".
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.services.chat_agent.agent import run_agent
from app.services.chat_agent.routing import should_force_topic_prefilter

# A b23-style cross-episode narrative question (≥2 discriminating tokens, no
# episode-scoped reference).
_B23_Q = "迪拉跟 Leo王 是怎麼從不認識變成合作夥伴的？他們第一次見面的故事是什麼？"


# ──────────────────────────────────────────────────────────────────────
# Detector tests
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, expected",
    [
        (_B23_Q, True),
        ("EP107 在講什麼？", False),
        ("第3集的內容是什麼", False),
        ("這集有哪些重點", False),
        ("歌單", False),  # single discriminating token
        ("", False),
        ("   ", False),
    ],
)
def test_should_force_topic_prefilter(question: str, expected: bool):
    assert should_force_topic_prefilter(question) is expected


# ──────────────────────────────────────────────────────────────────────
# run_agent tool_choice wiring
# ──────────────────────────────────────────────────────────────────────


def _db_mock() -> MagicMock:
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
    content: str | None, tool_calls_data: list[dict] | None = None
) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = (
        [_make_tool_call_obj(tc["id"], tc["name"], tc["args"]) for tc in tool_calls_data]
        if tool_calls_data
        else []
    )
    choice = MagicMock(message=msg, finish_reason="stop")
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


async def _run_with_responses(question: str, responses: list[MagicMock]) -> MagicMock:
    """Run run_agent with a fake OpenAI client returning `responses` in order.

    Returns the `create` AsyncMock so callers can assert on call_args_list.
    `_dispatch_tool` is stubbed so no real tool / DB executes.
    """
    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=responses)

    with (
        patch(
            "app.services.chat_agent.agent.get_step_config",
            return_value=_fake_step_config(),
        ),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client),
        patch("app.services.chat_agent.state._get_redis", return_value=_FakeRedis()),
        patch(
            "app.services.chat_agent.agent._dispatch_tool",
            new_callable=AsyncMock,
            return_value=({"ok": True, "episodes": []}, None, 1.0),
        ),
        patch(
            "app.services.chat_agent.agent._try_update_summary",
            new_callable=AsyncMock,
        ),
    ):
        await run_agent(question, uuid.uuid4(), uuid.uuid4(), _db_mock())

    return fake_client.chat.completions.create


@pytest.mark.asyncio
async def test_force_first_round_then_auto_when_hit_and_flag_on():
    """Detector hit + flag on → round 0 forces search_with_topic_prefilter,
    round 1 reverts to auto."""
    first = _make_llm_response(
        content=None,
        tool_calls_data=[
            {"id": "c1", "name": "search_with_topic_prefilter", "args": {"topic": "合作"}}
        ],
    )
    final = _make_llm_response(content="迪拉與 Leo 王在 EP107 初次合作。")

    with patch.object(settings, "enable_topic_routing_nudge", True):
        create = await _run_with_responses(_B23_Q, [first, final])

    assert create.call_count == 2
    assert create.call_args_list[0].kwargs["tool_choice"] == {
        "type": "function",
        "function": {"name": "search_with_topic_prefilter"},
    }
    assert create.call_args_list[1].kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_auto_when_hit_but_flag_off():
    """Detector hit + flag off → round 0 already uses auto (bit-equivalent to
    pre-change behaviour)."""
    final = _make_llm_response(content="這題我直接回答。")

    with patch.object(settings, "enable_topic_routing_nudge", False):
        create = await _run_with_responses(_B23_Q, [final])

    assert create.call_args_list[0].kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_auto_when_detector_miss():
    """Detector miss (episode-scoped question) + flag on → round 0 uses auto."""
    final = _make_llm_response(content="EP107 在講合作的故事。")

    with patch.object(settings, "enable_topic_routing_nudge", True):
        create = await _run_with_responses("EP107 在講什麼？", [final])

    assert create.call_args_list[0].kwargs["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_pinned_episode_guard_skips_force():
    """Detector hit + flag on BUT session has a focused/pinned episode →
    round 0 stays auto (pinned-episode guard, task 5 routing probe / mt02).

    A multi-turn follow-up that reads as a cross-episode topical question is
    episode-scoped by the pin; forcing cross-episode prefilter would override
    that scope.
    """
    from app.services.chat_agent.state import ChatSessionState

    focused = ChatSessionState(session_id=uuid.uuid4(), focused_episode_id=uuid.uuid4())
    final = _make_llm_response(content="他在那一集解釋了 RAG。")

    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=[final])

    with (
        patch.object(settings, "enable_topic_routing_nudge", True),
        patch(
            "app.services.chat_agent.agent.get_step_config",
            return_value=_fake_step_config(),
        ),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client),
        patch("app.services.chat_agent.state._get_redis", return_value=_FakeRedis()),
        patch(
            "app.services.chat_agent.agent.ChatSessionStateStore.load",
            return_value=focused,
        ),
        patch(
            "app.services.chat_agent.agent._dispatch_tool",
            new_callable=AsyncMock,
            return_value=({"ok": True}, None, 1.0),
        ),
        patch(
            "app.services.chat_agent.agent._try_update_summary",
            new_callable=AsyncMock,
        ),
    ):
        await run_agent("他怎麼解釋 RAG？", uuid.uuid4(), uuid.uuid4(), _db_mock())

    assert fake_client.chat.completions.create.call_args_list[0].kwargs[
        "tool_choice"
    ] == "auto"
