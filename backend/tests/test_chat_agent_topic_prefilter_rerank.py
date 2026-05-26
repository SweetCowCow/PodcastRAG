"""Tests for the rerank envelope contract in _search_with_topic_prefilter.

Change: retrieval-cross-episode-chunk-recovery (task 3.x).

This change initially attempted LLM-based rerank but discovered the AI Hub
provider consistently timed out on rerank-shape prompts (5 smoke iterations
in case study). The rerank stage is now disabled and the path falls back to
RRF top-k. The envelope still surfaces `rerank_applied` / `rerank_input_count`
fields so the follow-up Voyage/Cohere change can swap them in transparently.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.chat_agent.state import ChatSessionState
from app.services.chat_agent.tools import (
    SearchWithTopicPrefilterInput,
    ToolContext,
    _search_with_topic_prefilter,
)

SHOW = uuid.UUID("45fc2462-17cf-42f5-98a7-68fe1a222228")
EP143 = uuid.UUID("6c5ce32f-fb37-4aa0-b72c-7d14a7c1c163")


def _ctx() -> ToolContext:
    return ToolContext(
        db=MagicMock(),
        show_id=SHOW,
        state=ChatSessionState(session_id=uuid.uuid4()),
        state_store=MagicMock(),
    )


def _fake_hit(ep: uuid.UUID, start: float, text: str = "snippet"):
    return SimpleNamespace(
        chunk_id=uuid.uuid4(),
        episode_id=ep,
        episode_title="title",
        start_time=start,
        end_time=start + 30,
        text=text,
        rrf_score=0.05,
        source="transcript",
        before_text="",
        after_text="",
        highlights="",
        ai_summary_excerpt="",
        ai_summary_full=None,
        distance=None,
    )


@pytest.fixture
def patched(monkeypatch):
    from app.services.chat_agent import tools as mod

    state = {
        "candidates": [SimpleNamespace(episode_id=EP143)],
        "hits": [_fake_hit(EP143, float(i)) for i in range(5)],
        "retrieve_captured": {},
    }

    async def fake_finder(db, show_id, topics):
        return state["candidates"]

    async def fake_retrieve(db, *, show_id, query_embedding, question, k, episode_id_filter=None, **kw):
        state["retrieve_captured"]["k"] = k
        state["retrieve_captured"]["episode_id_filter"] = episode_id_filter
        return state["hits"]

    monkeypatch.setattr(mod.episode_finders, "find_episodes_by_topic", fake_finder)
    monkeypatch.setattr(mod, "_embed_query", AsyncMock(return_value=[0.0] * 8))
    monkeypatch.setattr(mod.rag, "retrieve_hybrid", fake_retrieve)

    return state


@pytest.mark.asyncio
async def test_prefilter_calls_retrieve_with_inp_k(patched):
    """retrieve_hybrid is invoked with k=inp.k (rerank disabled, no top-N expand)."""
    await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert patched["retrieve_captured"]["k"] == 5
    assert patched["retrieve_captured"]["episode_id_filter"] == [EP143]


@pytest.mark.asyncio
async def test_envelope_has_rerank_fields_disabled(patched):
    """Envelope still surfaces rerank fields (for follow-up compatibility), both False/0."""
    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert out["rerank_applied"] is False
    assert out["rerank_input_count"] == 0


@pytest.mark.asyncio
async def test_empty_candidate_envelope(patched):
    """Empty topic match → fallback envelope marks rerank_applied=False / count=0."""
    patched["candidates"] = []

    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="lorem-no-match", query="q", k=5), _ctx()
    )

    assert out["fallback_to_full_pool"] is True
    assert out["rerank_applied"] is False
    assert out["rerank_input_count"] == 0


@pytest.mark.asyncio
async def test_envelope_compatibility_with_old_consumers(patched):
    """Original envelope fields (chunks / prefilter_episode_count / fallback_to_full_pool) unchanged."""
    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert "chunks" in out
    assert out["prefilter_episode_count"] == 1
    assert out["fallback_to_full_pool"] is False
