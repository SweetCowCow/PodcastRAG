"""Tests for `chat_agent.memory` (chat-agentic-tool-routing change)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.services.chat_agent.memory import build_messages, update_history_summary
from app.services.chat_agent.state import ChatSessionState


@pytest.fixture
def state_blank() -> ChatSessionState:
    return ChatSessionState(session_id=uuid.uuid4())


def test_build_messages_blank_state_only_system_and_user(state_blank: ChatSessionState) -> None:
    msgs = build_messages(state_blank, history=[], question="hello")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "PodcastRAG" in msgs[0]["content"]
    # No focused / enumeration / summary lines when state is blank
    assert "Focused episode" not in msgs[0]["content"]
    assert "Last enumeration" not in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "hello"}


def test_build_messages_injects_focused_episode() -> None:
    ep = uuid.uuid4()
    s = ChatSessionState(
        session_id=uuid.uuid4(),
        focused_episode_id=ep,
        focused_episode_at=datetime.now(timezone.utc),
    )
    msgs = build_messages(s, history=[], question="q")
    assert f"Focused episode: {ep}" in msgs[0]["content"]


def test_build_messages_injects_enumeration_with_ordinal_instruction() -> None:
    eps = [uuid.uuid4() for _ in range(3)]
    s = ChatSessionState(
        session_id=uuid.uuid4(),
        last_enumeration_episodes=eps,
        last_enumeration_at=datetime.now(timezone.utc),
    )
    msgs = build_messages(s, history=[], question="第三集是什麼")
    sys_content = msgs[0]["content"]
    assert "Last enumeration:" in sys_content
    for ep in eps:
        assert str(ep) in sys_content
    assert "第 N 集" in sys_content
    assert "last_enumeration_episodes[N-1]" in sys_content
    # Anti-conflict guard: prompt must explicitly forbid find_episode_by_ref for ordinals
    assert "find_episode_by_ref" in sys_content


def test_build_messages_history_summary_as_second_system(state_blank: ChatSessionState) -> None:
    state_blank.history_summary = "prior summary text"
    msgs = build_messages(state_blank, history=[], question="q")
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "system"
    assert "prior summary text" in msgs[1]["content"]
    assert msgs[2] == {"role": "user", "content": "q"}


def test_build_messages_keeps_last_k_turns_preserving_tool_round_trip(
    state_blank: ChatSessionState,
) -> None:
    # 5 turns of history; only last 3 should be kept (default k_turns=3).
    # Turn 2 contains a tool round-trip; if it is sliced into the tail it
    # must come through whole.
    history = [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "turn 2"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "tool result"},
        {"role": "assistant", "content": "a2 final"},
        {"role": "user", "content": "turn 3"},
        {"role": "assistant", "content": "a3"},
        {"role": "user", "content": "turn 4"},
        {"role": "assistant", "content": "a4"},
        {"role": "user", "content": "turn 5"},
        {"role": "assistant", "content": "a5"},
    ]
    msgs = build_messages(state_blank, history=history, question="q now")
    # First sliced message should be "turn 3" (the (5-3)=3rd-from-last user turn)
    body = msgs[1:-1]  # drop system + trailing question
    assert body[0] == {"role": "user", "content": "turn 3"}
    # Trailing question still appended
    assert msgs[-1] == {"role": "user", "content": "q now"}


def test_summary_failure_fail_open_keeps_previous(state_blank: ChatSessionState) -> None:
    state_blank.history_summary = "previous summary"

    def boom(_prompt: str) -> str:
        raise RuntimeError("network unreachable")

    update_history_summary(
        state_blank,
        last_turn={"user": "hi", "assistant": "hello"},
        summarizer=boom,
    )
    # Fail-open: exception caught, previous summary retained, NOT cleared.
    assert state_blank.history_summary == "previous summary"


def test_summary_success_updates_and_truncates(state_blank: ChatSessionState) -> None:
    # Returns a 350-char summary that MUST be truncated to 300.
    long_text = "甲" * 350
    update_history_summary(
        state_blank,
        last_turn={"user": "u", "assistant": "a"},
        summarizer=lambda p: long_text,
    )
    assert len(state_blank.history_summary) == 300
    assert state_blank.history_summary == "甲" * 300
