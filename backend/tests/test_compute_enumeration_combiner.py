"""r3-3-chat-enum-grounding: combiner / dispatcher logic tests.

`_compute_enumeration_episodes` in `app.api.query` is the dispatcher that
reads the LLM-extracted entities + rule-pattern match state, decides
which `episode_finders` tool(s) to call, and combines results with
AND-with-fallback semantics. These tests cover the four spec-relevant
paths the design calls out:

  - topic-only trigger
  - guest+topic AND-intersect (non-empty)
  - guest+topic AND-intersect empty → fallback to guest-only
  - rule pattern with empty entities → topic terms from question
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.api import query as query_mod
from app.schemas.query import EpisodeRef
from app.schemas.query_entity import QueryEntities


def _ep(title: str) -> EpisodeRef:
    return EpisodeRef(
        episode_id=uuid.uuid4(), title=title,
        published_at=None, guests=[], ai_summary=None,
    )


# ---------------------------------------------------------------------------
# Topic-only trigger
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_topic_only_triggers_enum_dispatches_to_topic_finder(monkeypatch):
    """entities.topics non-empty (no guests, no date, no rule pattern) →
    combiner SHALL call `find_episodes_by_topic` and return its result."""
    target = _ep("EP歌單 1")

    captured = {}

    async def fake_find_by_topic(db, show_id, topic_terms):
        captured["called_with"] = list(topic_terms)
        return [target]

    monkeypatch.setattr(
        query_mod.episode_finders, "find_episodes_by_topic", fake_find_by_topic
    )
    # Make absolutely sure guest / date finders are NOT invoked
    async def _should_not_call_guest(*a, **kw):
        raise AssertionError("find_episodes_by_guest must not be called")
    async def _should_not_call_date(*a, **kw):
        raise AssertionError("find_episodes_by_date_range must not be called")
    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_guest", _should_not_call_guest)
    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_date_range", _should_not_call_date)

    episodes, marker = await query_mod._compute_enumeration_episodes(
        AsyncMock(), uuid.uuid4(),
        question="歌單",
        entities=QueryEntities(topics=["歌單"]),
    )
    assert episodes == [target]
    assert marker == "none"
    assert captured["called_with"] == ["歌單"]


# ---------------------------------------------------------------------------
# Guest + Topic AND intersect (non-empty)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guest_and_topic_intersect_keeps_only_common_episodes(monkeypatch):
    """Both filters return non-empty lists; combiner SHALL emit only
    episodes whose episode_id appears in BOTH sets."""
    shared = _ep("EP143 共同")
    guest_only = _ep("EP140 only-guest")
    topic_only = _ep("EP歌單 only-topic")

    async def fake_find_by_guest(db, show_id, guests):
        return [shared, guest_only]

    async def fake_find_by_topic(db, show_id, topic_terms):
        return [shared, topic_only]

    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_guest", fake_find_by_guest)
    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_topic", fake_find_by_topic)

    episodes, marker = await query_mod._compute_enumeration_episodes(
        AsyncMock(), uuid.uuid4(),
        question="馬世芳那幾集講過家常菜",
        entities=QueryEntities(guests=["馬世芳"], topics=["家常菜"]),
    )
    ids = [e.episode_id for e in episodes]
    assert ids == [shared.episode_id]
    assert marker == "none"


# ---------------------------------------------------------------------------
# Guest + Topic AND empty → fallback to guest-only
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guest_topic_intersection_empty_falls_back_to_guest_only(monkeypatch):
    """When the AND intersection is empty AND guest-only filter has
    results, combiner SHALL return guest-only results with marker
    'guest_only' so the answer prompt can warn the user."""
    guest_eps = [_ep("EP140"), _ep("EP143")]
    topic_eps = [_ep("EP歌單")]  # no overlap with guest_eps

    async def fake_find_by_guest(db, show_id, guests):
        return guest_eps

    async def fake_find_by_topic(db, show_id, topic_terms):
        return topic_eps

    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_guest", fake_find_by_guest)
    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_topic", fake_find_by_topic)

    episodes, marker = await query_mod._compute_enumeration_episodes(
        AsyncMock(), uuid.uuid4(),
        question="馬世芳那幾集講過烤肉",
        entities=QueryEntities(guests=["馬世芳"], topics=["烤肉"]),
    )
    assert [e.episode_id for e in episodes] == [e.episode_id for e in guest_eps]
    assert marker == "guest_only"


@pytest.mark.asyncio
async def test_guest_topic_intersection_empty_and_no_guest_results_stays_empty(monkeypatch):
    """If guest-only finder also returns nothing, no fallback can apply
    — result is empty list with marker 'none' (not 'guest_only')."""
    async def fake_find_by_guest(db, show_id, guests):
        return []

    async def fake_find_by_topic(db, show_id, topic_terms):
        return [_ep("EP歌單")]

    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_guest", fake_find_by_guest)
    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_topic", fake_find_by_topic)

    episodes, marker = await query_mod._compute_enumeration_episodes(
        AsyncMock(), uuid.uuid4(),
        question="林志炫那幾集講過烤肉",
        entities=QueryEntities(guests=["林志炫"], topics=["烤肉"]),
    )
    assert episodes == []
    assert marker == "none"


# ---------------------------------------------------------------------------
# Rule pattern with empty entities → topic terms from question
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rule_pattern_uses_question_topic_terms(monkeypatch):
    """When rule pattern matches but LLM extracted nothing, combiner
    SHALL derive topic terms from the question via
    `extract_topic_terms_from_question` and call the topic finder.
    The previous 'list every episode' fallback path is gone."""
    captured = {}

    async def fake_find_by_topic(db, show_id, topic_terms):
        captured["called_with"] = list(topic_terms)
        return [_ep("EP歌單")]

    async def _no_call(*a, **kw):
        raise AssertionError("guest/date finder must not be called on rule-pattern-only path")

    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_topic", fake_find_by_topic)
    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_guest", _no_call)
    monkeypatch.setattr(query_mod.episode_finders, "find_episodes_by_date_range", _no_call)

    episodes, marker = await query_mod._compute_enumeration_episodes(
        AsyncMock(), uuid.uuid4(),
        question="歌單哪幾集",
        entities=QueryEntities.empty(),
    )
    assert len(episodes) == 1
    assert marker == "none"
    # Topic terms were derived from question, NOT from entities.topics
    # (which was empty). The exact terms depend on jieba but the call
    # MUST have happened with a list (possibly with stopwords filtered).
    assert "called_with" in captured
    assert isinstance(captured["called_with"], list)
    # `哪幾集` is in TOPIC_STOPWORDS so it MUST NOT appear
    assert "哪幾集" not in captured["called_with"]
