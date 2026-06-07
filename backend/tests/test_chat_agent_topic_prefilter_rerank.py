"""Integration tests for Voyage rerank inside _search_with_topic_prefilter.

Change: retrieval-rerank-via-voyage task 3.2. Replaces the noop-rerank tests
left by retrieval-cross-episode-chunk-recovery.
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
    """Common mocks; tests mutate `state` to control behavior per case."""
    from app.services.chat_agent import tools as mod

    state = {
        "candidates": [SimpleNamespace(episode_id=EP143)],
        "hits": [_fake_hit(EP143, float(i)) for i in range(_PREFILTER_RERANK_TOP_N)],
        "voyage_result": None,  # (chunks, applied) or None for identity
        "retrieve_captured": {},
        "voyage_captured": {},
    }

    async def fake_finder(db, show_id, topics, *, query=None):
        # query forwarded by _search_with_topic_prefilter
        # (topic-prefilter-forward-query-tokens); accept & ignore here.
        return state["candidates"], "topic_index"

    async def fake_retrieve(db, *, show_id, query_embedding, question, k, episode_id_filter=None, **kw):
        state["retrieve_captured"]["k"] = k
        state["retrieve_captured"]["episode_id_filter"] = episode_id_filter
        return state["hits"]

    async def fake_voyage(question, chunks, k, *, client, **kw):
        state["voyage_captured"]["called"] = True
        state["voyage_captured"]["chunks_len"] = len(chunks)
        state["voyage_captured"]["k"] = k
        if state["voyage_result"] is not None:
            return state["voyage_result"]
        return chunks[:k], True

    # Ensure VOYAGE_API_KEY appears set so the prefilter path takes the rerank
    # branch rather than the unset-key fallback.
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
    monkeypatch.setattr(mod.episode_finders, "find_episodes_by_topic_with_source", fake_finder)
    monkeypatch.setattr(mod, "_embed_query", AsyncMock(return_value=[0.0] * 8))
    monkeypatch.setattr(mod.rag, "retrieve_hybrid", fake_retrieve)
    monkeypatch.setattr(mod.rag_rerank, "voyage_rerank", fake_voyage)

    return state


@pytest.mark.asyncio
async def test_prefilter_calls_retrieve_with_k30(patched):
    """retrieve_hybrid is invoked with k=_PREFILTER_RERANK_TOP_N (=30), not inp.k."""
    await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert patched["retrieve_captured"]["k"] == _PREFILTER_RERANK_TOP_N == 30
    assert patched["retrieve_captured"]["episode_id_filter"] == [EP143]


@pytest.mark.asyncio
async def test_prefilter_calls_voyage_rerank(patched):
    """voyage_rerank is called with the full top_n chunk list and inp.k."""
    await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert patched["voyage_captured"]["called"] is True
    assert patched["voyage_captured"]["chunks_len"] == _PREFILTER_RERANK_TOP_N
    assert patched["voyage_captured"]["k"] == 5


@pytest.mark.asyncio
async def test_envelope_rerank_applied_true_on_success(patched):
    """Envelope reports rerank_applied=True when Voyage succeeds."""
    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert out["rerank_applied"] is True
    assert out["rerank_input_count"] == _PREFILTER_RERANK_TOP_N


@pytest.mark.asyncio
async def test_envelope_rerank_applied_false_on_failure(patched):
    """When voyage_rerank returns applied=False (timeout/api error fallback)."""
    patched["voyage_result"] = (
        [
            {"chunk_id": str(patched["hits"][i].chunk_id), "episode_id": str(EP143), "start_time": float(i)}
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
async def test_empty_candidate_skips_rerank(patched):
    """Empty topic match → fallback path doesn't call rerank."""
    patched["candidates"] = []
    patched["voyage_captured"].clear()

    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="lorem-no-match", query="q", k=5), _ctx()
    )

    assert out["fallback_to_full_pool"] is True
    assert out["rerank_applied"] is False
    assert out["rerank_input_count"] == 0
    assert "called" not in patched["voyage_captured"]


@pytest.mark.asyncio
async def test_envelope_compatibility_with_old_consumers(patched):
    """Pre-existing envelope fields untouched (chunks / prefilter_episode_count / fallback_to_full_pool)."""
    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q", k=5), _ctx()
    )
    assert "chunks" in out
    assert out["prefilter_episode_count"] == 1
    assert out["fallback_to_full_pool"] is False
