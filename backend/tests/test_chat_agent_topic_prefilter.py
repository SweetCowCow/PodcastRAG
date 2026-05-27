"""Tests for search_with_topic_prefilter tool (change: retrieval-cross-episode-episode-prefilter)."""
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
EP107 = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _ctx() -> ToolContext:
    return ToolContext(
        db=MagicMock(),
        show_id=SHOW,
        state=ChatSessionState(session_id=uuid.uuid4()),
        state_store=MagicMock(),
    )


# NOTE: an earlier draft of retrieval-cross-episode-chunk-recovery wired the
# prefilter path through rag_rerank.llm_rerank, requiring autouse mocks here.
# That path was disabled (5 timeout iterations on AI Hub — see case study);
# rerank is now a no-op until the Voyage/Cohere follow-up. Autouse mock removed.


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


@pytest.mark.asyncio
async def test_prefilter_scopes_to_candidates(monkeypatch):
    """Topic match returns 2 episodes → retrieve_hybrid called with that filter, no out-of-set chunks."""
    from app.services.chat_agent import tools as mod

    candidates = [
        SimpleNamespace(episode_id=EP143),
        SimpleNamespace(episode_id=EP107),
    ]
    monkeypatch.setattr(
        mod.episode_finders, "find_episodes_by_topic_with_source",
        AsyncMock(return_value=(candidates, "topic_index")),
    )
    monkeypatch.setattr(mod, "_embed_query", AsyncMock(return_value=[0.0] * 8))

    captured: dict = {}

    async def fake_retrieve(db, *, show_id, query_embedding, question, k, episode_id_filter=None, **kw):
        captured["episode_id_filter"] = episode_id_filter
        captured["k"] = k
        return [_fake_hit(EP143, 100.0), _fake_hit(EP107, 200.0)]

    monkeypatch.setattr(mod.rag, "retrieve_hybrid", fake_retrieve)

    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="家常味", query="馬世芳怎麼定義家常味", k=5),
        _ctx(),
    )

    assert captured["episode_id_filter"] == [EP143, EP107]
    assert out["prefilter_episode_count"] == 2
    assert out["fallback_to_full_pool"] is False
    # No out-of-set chunks
    for c in out["chunks"]:
        assert uuid.UUID(c["episode_id"]) in {EP143, EP107}


@pytest.mark.asyncio
async def test_prefilter_empty_falls_back(monkeypatch):
    """Topic match returns 0 episodes → retrieve_hybrid called WITHOUT filter, fallback flag set."""
    from app.services.chat_agent import tools as mod

    monkeypatch.setattr(
        mod.episode_finders, "find_episodes_by_topic_with_source",
        AsyncMock(return_value=([], "topic_index")),
    )
    monkeypatch.setattr(mod, "_embed_query", AsyncMock(return_value=[0.0] * 8))

    captured: dict = {}

    async def fake_retrieve(db, *, show_id, query_embedding, question, k, episode_id_filter=None, **kw):
        captured["episode_id_filter"] = episode_id_filter
        return [_fake_hit(EP143, 50.0)]

    monkeypatch.setattr(mod.rag, "retrieve_hybrid", fake_retrieve)

    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="lorem-ipsum-no-match", query="any", k=5),
        _ctx(),
    )

    assert "episode_id_filter" not in captured or captured["episode_id_filter"] is None
    assert out["prefilter_episode_count"] == 0
    assert out["fallback_to_full_pool"] is True
    assert len(out["chunks"]) == 1


@pytest.mark.asyncio
async def test_envelope_fields_always_populated(monkeypatch):
    """Both happy + fallback paths populate chunks / prefilter_episode_count / fallback_to_full_pool."""
    from app.services.chat_agent import tools as mod

    monkeypatch.setattr(mod, "_embed_query", AsyncMock(return_value=[0.0] * 8))

    async def fake_retrieve(db, **kw):
        return [_fake_hit(EP143, 1.0)]

    monkeypatch.setattr(mod.rag, "retrieve_hybrid", fake_retrieve)

    # Path 1: with candidates
    monkeypatch.setattr(
        mod.episode_finders, "find_episodes_by_topic_with_source",
        AsyncMock(return_value=([SimpleNamespace(episode_id=EP143)], "topic_index")),
    )
    out1 = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q"), _ctx()
    )
    assert set(out1.keys()) >= {"chunks", "prefilter_episode_count", "fallback_to_full_pool"}

    # Path 2: empty candidates → fallback
    monkeypatch.setattr(
        mod.episode_finders, "find_episodes_by_topic_with_source",
        AsyncMock(return_value=([], "topic_index")),
    )
    out2 = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="Y", query="q"), _ctx()
    )
    assert set(out2.keys()) >= {"chunks", "prefilter_episode_count", "fallback_to_full_pool"}


@pytest.mark.asyncio
async def test_chunk_dict_shape_matches_existing_tools(monkeypatch):
    """Returned chunk dict has the same shape as _search_across_episodes output (via _chunk_to_dict)."""
    from app.services.chat_agent import tools as mod

    monkeypatch.setattr(
        mod.episode_finders, "find_episodes_by_topic_with_source",
        AsyncMock(return_value=([SimpleNamespace(episode_id=EP143)], "topic_index")),
    )
    monkeypatch.setattr(mod, "_embed_query", AsyncMock(return_value=[0.0] * 8))

    async def fake_retrieve(db, **kw):
        return [_fake_hit(EP143, 42.0)]

    monkeypatch.setattr(mod.rag, "retrieve_hybrid", fake_retrieve)

    out = await _search_with_topic_prefilter(
        SearchWithTopicPrefilterInput(topic="X", query="q"), _ctx()
    )
    chunk = out["chunks"][0]
    # _chunk_to_dict produces these keys (mirror from tools.py)
    expected_keys = {
        "chunk_id", "episode_id", "episode_title", "start_time", "end_time",
        "text", "rrf_score", "source",
    }
    assert expected_keys.issubset(set(chunk.keys()))
    assert chunk["episode_id"] == str(EP143)
    assert chunk["start_time"] == 42.0
