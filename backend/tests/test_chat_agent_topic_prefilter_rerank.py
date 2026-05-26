"""Tests for rerank wiring inside _search_with_topic_prefilter.

Change: retrieval-cross-episode-chunk-recovery (task 3.x).
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
    _PREFILTER_RERANK_TOP_N,
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
    """Set up common mocks; return a dict the caller mutates per test."""
    from app.services.chat_agent import tools as mod

    state = {
        "candidates": [SimpleNamespace(episode_id=EP143)],
        "hits": [_fake_hit(EP143, float(i)) for i in range(_PREFILTER_RERANK_TOP_N)],
        "rerank_result": None,  # (chunks, applied) or None to use identity
        "retrieve_captured": {},
        "rerank_captured": {},
    }

    async def fake_finder(db, show_id, topics):
        return state["candidates"]

    async def fake_retrieve(db, *, show_id, query_embedding, question, k, episode_id_filter=None, **kw):
        state["retrieve_captured"]["k"] = k
        state["retrieve_captured"]["episode_id_filter"] = episode_id_filter
        return state["hits"]

    async def fake_rerank(question, chunks, k, *, client, **kw):
        state["rerank_captured"]["called"] = True
        state["rerank_captured"]["chunks_len"] = len(chunks)
        state["rerank_captured"]["k"] = k
        if state["rerank_result"] is not None:
            return state["rerank_result"]
        return chunks[:k], True

    monkeypatch.setattr(mod.episode_finders, "find_episodes_by_topic", fake_finder)
    monkeypatch.setattr(mod, "_embed_query", AsyncMock(return_value=[0.0] * 8))
    monkeypatch.setattr(mod.rag, "retrieve_hybrid", fake_retrieve)
    monkeypatch.setattr(
        mod, "get_step_config",
        AsyncMock(return_value=SimpleNamespace(base_url="http://stub", api_key="k", model="m")),
    )
    monkeypatch.setattr(mod.rag_rerank, "llm_rerank", fake_rerank)

    return state


@pytest.mark.asyncio
async def test_prefilter_calls_retrieve_with_k50(patched):
    """retrieve_hybrid is invoked with k=_PREFILTER_RERANK_TOP_N (=50), not inp.k."""
    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert patched["retrieve_captured"]["k"] == _PREFILTER_RERANK_TOP_N
    assert patched["retrieve_captured"]["episode_id_filter"] == [EP143]
    assert len(out["chunks"]) == 5


@pytest.mark.asyncio
async def test_prefilter_calls_rerank_after_retrieve(patched):
    """rerank is called with the full top_n chunk list."""
    await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert patched["rerank_captured"]["called"] is True
    assert patched["rerank_captured"]["chunks_len"] == _PREFILTER_RERANK_TOP_N
    assert patched["rerank_captured"]["k"] == 5


@pytest.mark.asyncio
async def test_envelope_has_rerank_fields(patched):
    """Envelope includes rerank_applied + rerank_input_count on the prefilter path."""
    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert out["rerank_applied"] is True
    assert out["rerank_input_count"] == _PREFILTER_RERANK_TOP_N


@pytest.mark.asyncio
async def test_empty_candidate_skips_rerank(patched):
    """Empty topic match → no rerank, fallback envelope marks rerank_applied=False / count=0."""
    patched["candidates"] = []
    # Reset rerank tracking — fallback path SHALL NOT call rerank.
    patched["rerank_captured"].clear()

    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="lorem-no-match", query="q", k=5), _ctx()
    )

    assert out["fallback_to_full_pool"] is True
    assert out["rerank_applied"] is False
    assert out["rerank_input_count"] == 0
    assert "called" not in patched["rerank_captured"]


@pytest.mark.asyncio
async def test_rerank_failure_returns_rrf_top_k(patched):
    """When rerank returns applied=False, the tool surfaces that and still returns top-k chunks."""
    # Override rerank to simulate failure → returns first k input chunks + applied=False.
    patched["rerank_result"] = (
        [
            {
                "chunk_id": str(patched["hits"][i].chunk_id),
                "episode_id": str(EP143),
                "start_time": float(i),
            }
            for i in range(5)
        ],
        False,
    )

    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert out["rerank_applied"] is False
    assert out["rerank_input_count"] == _PREFILTER_RERANK_TOP_N
    assert len(out["chunks"]) == 5


@pytest.mark.asyncio
async def test_envelope_compatibility_with_old_consumers(patched):
    """Original envelope fields (chunks / prefilter_episode_count / fallback_to_full_pool) unchanged."""
    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert "chunks" in out
    assert out["prefilter_episode_count"] == 1
    assert out["fallback_to_full_pool"] is False
