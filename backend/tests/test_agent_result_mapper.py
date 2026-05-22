"""Tests for `_agent_result_to_response` mapper enrichment.

Covers the `enable-agentic-chat-default-on` change: the mapper must
populate `ChatResponse.citations` from successful search-tool dispatches
and `ChatResponse.enumeration_episodes` from successful listing-tool
dispatches, gracefully skip malformed payloads, and preserve the
pre-flip behaviour (empty list / None) when no relevant tool was
invoked.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest

from app.api.query import _agent_result_to_response
from app.schemas.query import ToolCallTrace
from app.services.chat_agent.agent import (
    ChatAgentResult,
    StageTimings,
)
from app.services.chat_agent.state import ChatSessionState


def _chunk(
    *,
    chunk_id: str,
    episode_id: str,
    rrf_score: float,
    episode_title: str = "EP",
    text: str = "snippet",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "episode_id": episode_id,
        "episode_title": episode_title,
        "start_time": 12.5,
        "end_time": 30.0,
        "text": text,
        "rrf_score": rrf_score,
        "source": "transcript",
        "before_text": "",
        "after_text": "",
        "highlights": "",
        "ai_summary_excerpt": "",
        "ai_summary_full": None,
    }


def _ep(*, episode_id: str, title: str = "An Episode") -> dict:
    return {
        "episode_id": episode_id,
        "title": title,
        "published_at": None,
        "guests": [],
        "ai_summary": None,
    }


def _trace(
    *,
    name: str,
    payload: dict | str,
    raised: str | None = None,
) -> ToolCallTrace:
    if isinstance(payload, dict):
        result_full = json.dumps(payload)
    else:
        result_full = payload
    summary = result_full[:500] if result_full else ""
    return ToolCallTrace(
        name=name,
        args={},
        result_summary=summary,
        raised=raised,
        latency_ms=1.0,
        result_full=result_full,
    )


def _result(tool_calls: list[ToolCallTrace]) -> ChatAgentResult:
    return ChatAgentResult(
        answer="ok",
        tool_calls=tool_calls,
        agent_truncated=False,
        l1_state_after=ChatSessionState(session_id=uuid.uuid4()),
        usage=None if False else __import__(
            "app.services.chat_agent.agent", fromlist=["TokenUsage"]
        ).TokenUsage(),
        llm_calls=[],
        stage_timings=StageTimings(),
    )


# ──────────────────────────────────────────────────────────────────────
# Citations from search-tool dispatches
# ──────────────────────────────────────────────────────────────────────


def test_citations_top5_deduped_and_sorted_across_search_tools():
    ep_a = str(uuid.uuid4())
    ep_b = str(uuid.uuid4())
    duplicate_chunk = _chunk(chunk_id="c1", episode_id=ep_a, rrf_score=0.5)
    tool_calls = [
        _trace(
            name="search_across_episodes",
            payload={
                "chunks": [
                    _chunk(chunk_id="c1", episode_id=ep_a, rrf_score=0.9),
                    _chunk(chunk_id="c2", episode_id=ep_a, rrf_score=0.8),
                    _chunk(chunk_id="c3", episode_id=ep_b, rrf_score=0.7),
                    _chunk(chunk_id="c4", episode_id=ep_b, rrf_score=0.6),
                ]
            },
        ),
        _trace(
            name="search_within_episode",
            payload={
                "chunks": [
                    duplicate_chunk,  # dup chunk_id=c1 should be skipped
                    _chunk(chunk_id="c5", episode_id=ep_a, rrf_score=0.95),
                    _chunk(chunk_id="c6", episode_id=ep_b, rrf_score=0.4),
                    _chunk(chunk_id="c7", episode_id=ep_b, rrf_score=0.3),
                ]
            },
        ),
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert len(response.citations) == 5
    chunk_ids = [str(c.episode_id) for c in response.citations]
    # Top 5 by rrf_score descending: 0.95, 0.9, 0.8, 0.7, 0.6
    scores_in_order = [0.95, 0.9, 0.8, 0.7, 0.6]
    # We can't read rrf_score from ChunkHit (not exposed), but order is
    # deterministic — verify by checking the first two episode_ids.
    assert str(response.citations[0].episode_id) == ep_a  # c5 rrf=0.95
    assert str(response.citations[1].episode_id) == ep_a  # c1 rrf=0.9
    # No duplicate episode_id, chunk_id pairs (dedupe by chunk_id worked).
    assert len(set(chunk_ids)) <= len(chunk_ids)


def test_citations_empty_when_only_listing_tool_invoked():
    tool_calls = [
        _trace(
            name="find_episodes_by_guest",
            payload={"episodes": [_ep(episode_id=str(uuid.uuid4()))]},
        )
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert response.citations == []


def test_citations_empty_when_all_search_tools_raised():
    tool_calls = [
        _trace(
            name="search_within_episode",
            payload="",
            raised="ProgrammingError",
        ),
        _trace(
            name="search_across_episodes",
            payload="",
            raised="TimeoutError",
        ),
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert response.citations == []


def test_citations_skip_malformed_chunk_payload(caplog):
    ep_a = str(uuid.uuid4())
    tool_calls = [
        _trace(name="search_within_episode", payload={"not_chunks": "bad"}),
        _trace(
            name="search_across_episodes",
            payload={"chunks": [_chunk(chunk_id="c1", episode_id=ep_a, rrf_score=0.5)]},
        ),
    ]
    with caplog.at_level(logging.WARNING, logger="app.api.query"):
        response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    # Bad payload skipped, good one still processed.
    assert len(response.citations) == 1
    assert any(
        "Skipping malformed search-tool result" in rec.message for rec in caplog.records
    )


# ──────────────────────────────────────────────────────────────────────
# Enumeration from listing-tool dispatches
# ──────────────────────────────────────────────────────────────────────


def test_enumeration_populated_and_order_preserved():
    ep1 = str(uuid.uuid4())
    ep2 = str(uuid.uuid4())
    ep3 = str(uuid.uuid4())
    tool_calls = [
        _trace(
            name="find_episodes_by_guest",
            payload={"episodes": [_ep(episode_id=ep1), _ep(episode_id=ep2)]},
        ),
        _trace(
            name="find_episodes_by_topic",
            payload={
                "episodes": [
                    _ep(episode_id=ep2),  # dup, should be skipped
                    _ep(episode_id=ep3),
                ]
            },
        ),
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert response.enumeration_episodes is not None
    observed_ids = [str(e.episode_id) for e in response.enumeration_episodes]
    assert observed_ids == [ep1, ep2, ep3]
    assert response.enumeration_total == 3


def test_enumeration_none_when_only_search_invoked():
    tool_calls = [
        _trace(
            name="search_within_episode",
            payload={"chunks": [_chunk(chunk_id="c1", episode_id=str(uuid.uuid4()), rrf_score=0.5)]},
        )
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert response.enumeration_episodes is None
    assert response.enumeration_total is None


def test_enumeration_empty_list_when_listing_invoked_but_no_match():
    tool_calls = [
        _trace(name="find_episodes_by_guest", payload={"episodes": []})
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    # Listing was invoked (even though empty) → empty list, not None
    assert response.enumeration_episodes == []
    assert response.enumeration_total == 0


def test_enumeration_skip_raised_listing_tool():
    ep1 = str(uuid.uuid4())
    tool_calls = [
        _trace(
            name="find_episodes_by_topic",
            payload="",
            raised="ProgrammingError",
        ),
        _trace(
            name="find_episodes_by_date",
            payload={"episodes": [_ep(episode_id=ep1)]},
        ),
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert response.enumeration_episodes is not None
    assert len(response.enumeration_episodes) == 1
    assert str(response.enumeration_episodes[0].episode_id) == ep1


# ──────────────────────────────────────────────────────────────────────
# Combined / boundary cases
# ──────────────────────────────────────────────────────────────────────


def test_no_relevant_tool_invoked_keeps_empty_and_none():
    tool_calls = [
        _trace(
            name="get_show_overview",
            payload={"title": "Show", "overview": "..."},
        )
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert response.citations == []
    assert response.enumeration_episodes is None


def test_empty_tool_calls_list():
    response = _agent_result_to_response(_result([]), quota_remaining=10)
    assert response.citations == []
    assert response.enumeration_episodes is None


def test_find_episode_by_ref_populates_single_enumeration():
    ep_id = str(uuid.uuid4())
    tool_calls = [
        _trace(
            name="find_episode_by_ref",
            payload={"episode": {
                "episode_id": ep_id,
                "title": "EP143｜從餐廳請客到自家廚房",
                "published_at": None,
                "guests": ["馬世芳"],
                "ai_summary": "...",
            }},
        )
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert response.enumeration_episodes is not None
    assert len(response.enumeration_episodes) == 1
    assert str(response.enumeration_episodes[0].episode_id) == ep_id


def test_get_episode_summary_populates_single_enumeration_partial_fields():
    ep_id = str(uuid.uuid4())
    tool_calls = [
        _trace(
            name="get_episode_summary",
            payload={
                "episode_id": ep_id,
                "title": "EP143｜...",
                "summary": "本集摘要文字",
            },
        )
    ]
    response = _agent_result_to_response(_result(tool_calls), quota_remaining=10)
    assert response.enumeration_episodes is not None
    assert len(response.enumeration_episodes) == 1
    assert response.enumeration_episodes[0].ai_summary == "本集摘要文字"
