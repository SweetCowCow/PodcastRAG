"""Regression test for multi-turn ordinal reference (chat-agentic-tool-routing).

This is the bake-off three-framework-all-fail scenario:
  Turn 1: "歌單有哪幾集？"  → agent calls find_episodes_by_topic,
                              L1 state.last_enumeration_episodes is populated.
  Turn 2: "第三集是什麼內容？" → agent should call get_episode_summary(episode_id=last_enumeration[2]),
                              NOT find_episode_by_ref(ref="EP3") or similar.

Decision reference: design.md Decision "Multi-turn carry 用 ordinal-aware system prompt instruction"
Spec verification target: design.md Implementation Contract §agent.py
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.schemas.query import EpisodeRef
from datetime import datetime, timezone
from app.services.chat_agent.agent import run_agent
from app.services.chat_agent.state import ChatSessionState, ChatSessionStateStore


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
# The regression test
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enumeration_then_ordinal_reference():
    """Two-turn conversation regression:

    Turn 1: "歌單有哪幾集？"
      → find_episodes_by_topic("歌單") is called
      → L1 state.last_enumeration_episodes is populated with returned ep IDs

    Turn 2 (same session): "第三集是什麼內容？"
      → get_episode_summary(episode_id=last_enumeration_episodes[2]) is called
      → find_episode_by_ref(ref="EP3") is NOT called

    Design decision: The ordinal instruction in the system prompt teaches the
    LLM to resolve "第 N 集" using last_enumeration_episodes[N-1].
    This was the scenario all three bake-off frameworks failed without the fix.
    """
    session_id = uuid.uuid4()
    show_id = uuid.uuid4()

    # Three episodes returned by the enumeration tool (turn 1)
    ep_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    fake_episodes = [
        EpisodeRef(episode_id=ep_id, title=f"歌單 EP{100+i}", published_at=datetime(2024, 1, i+1, tzinfo=timezone.utc))
        for i, ep_id in enumerate(ep_ids)
    ]

    fake_redis = _FakeRedis()

    # ── Turn 1: "歌單有哪幾集？" ──
    t1_tool_resp = _make_llm_response(
        content=None,
        tool_calls_data=[
            {"id": "c1", "name": "find_episodes_by_topic", "args": {"topic": "歌單"}}
        ],
    )
    t1_answer_resp = _make_llm_response(content="歌單共有 3 集：EP100、EP101、EP102。")

    fake_client_t1 = AsyncMock()
    fake_client_t1.chat.completions.create = AsyncMock(
        side_effect=[t1_tool_resp, t1_answer_resp]
    )

    with (
        patch("app.services.chat_agent.agent.get_step_config", return_value=_fake_step_config()),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client_t1),
        patch("app.services.chat_agent.state._get_redis", return_value=fake_redis),
        patch(
            "app.services.chat_agent.tools.episode_finders.find_episodes_by_topic",
            new_callable=AsyncMock,
            return_value=fake_episodes,
        ),
        patch("app.services.chat_agent.agent._try_update_summary", new_callable=AsyncMock),
    ):
        result_t1 = await run_agent("歌單有哪幾集？", session_id, show_id, AsyncMock())

    # Assert turn 1: find_episodes_by_topic was called
    tool_names_t1 = [tc.name for tc in result_t1.tool_calls]
    assert "find_episodes_by_topic" in tool_names_t1, (
        "Turn 1: expected find_episodes_by_topic to be called"
    )

    # Assert L1 state was persisted with the episode IDs
    state_after_t1 = result_t1.l1_state_after
    assert len(state_after_t1.last_enumeration_episodes) == 3, (
        "Turn 1: L1 state should have 3 enumeration episodes"
    )
    assert set(state_after_t1.last_enumeration_episodes) == set(ep_ids)

    # ── Turn 2: "第三集是什麼內容？" (same session_id) ──
    # The third episode (index 2) is ep_ids[2]
    third_ep_id = ep_ids[2]

    # LLM should call get_episode_summary with the correct ep_id from L1 state
    t2_tool_resp = _make_llm_response(
        content=None,
        tool_calls_data=[
            {"id": "c2", "name": "get_episode_summary", "args": {"episode_id": str(third_ep_id)}}
        ],
    )
    t2_answer_resp = _make_llm_response(content=f"第三集 EP102 的摘要是：...")

    fake_client_t2 = AsyncMock()
    fake_client_t2.chat.completions.create = AsyncMock(
        side_effect=[t2_tool_resp, t2_answer_resp]
    )

    # Mock the DB call for get_episode_summary
    fake_db_t2 = AsyncMock()
    result_mock = MagicMock()
    result_mock.mappings.return_value.first.return_value = {
        "title": "歌單 EP102",
        "ai_summary": "第三集摘要",
    }
    fake_db_t2.execute = AsyncMock(return_value=result_mock)

    with (
        patch("app.services.chat_agent.agent.get_step_config", return_value=_fake_step_config()),
        patch("app.services.chat_agent.agent.AsyncOpenAI", return_value=fake_client_t2),
        patch("app.services.chat_agent.state._get_redis", return_value=fake_redis),
        patch("app.services.chat_agent.agent._try_update_summary", new_callable=AsyncMock),
    ):
        result_t2 = await run_agent("第三集是什麼內容？", session_id, show_id, fake_db_t2)

    # Assert turn 2: get_episode_summary was called with the correct episode
    tool_names_t2 = [tc.name for tc in result_t2.tool_calls]
    assert "get_episode_summary" in tool_names_t2, (
        "Turn 2: expected get_episode_summary to be called"
    )

    # Assert find_episode_by_ref was NOT called (the bake-off regression)
    assert "find_episode_by_ref" not in tool_names_t2, (
        "Turn 2: find_episode_by_ref must NOT be called — "
        "ordinal should resolve via last_enumeration_episodes, not EP-number lookup"
    )

    # Assert the correct episode_id was passed to get_episode_summary
    summary_call = next(tc for tc in result_t2.tool_calls if tc.name == "get_episode_summary")
    called_ep_id = uuid.UUID(summary_call.args["episode_id"])
    assert called_ep_id == third_ep_id, (
        f"Turn 2: get_episode_summary called with {called_ep_id}, "
        f"expected last_enumeration_episodes[2] = {third_ep_id}"
    )
