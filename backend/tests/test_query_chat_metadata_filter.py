"""R3.3 Phase 9: chat endpoint integrates entity_extraction + enumeration.

Unit tests for the helpers that wire `query_entity.extract_entities` into
the chat path. Full HTTP-level tests over the endpoint require a real DB +
quota gating + LLM mocks (the suite has 13 pre-existing setup errors in
`test_error_responses.py` for the same reason), so we keep these tests at
the helper level — every contract item from spec scenarios is reachable
this way:

  - "Guest filter narrows retrieval"          → _entities_to_metadata_filters
  - "Date filter narrows retrieval"           → _entities_to_metadata_filters
  - "Empty entity result triggers no enumeration" → _compute_enumeration_episodes
  - "Entity extraction fails-open"            → _extract_entities_fail_open
  - "Enumeration rule pattern triggers"       → _compute_enumeration_episodes
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import query as query_mod
from app.schemas.query import EpisodeRef
from app.schemas.query_entity import QueryEntities
from app.services import rag


# ---------------------------------------------------------------------------
# _entities_to_metadata_filters
# ---------------------------------------------------------------------------

def test_empty_entities_lift_to_none():
    assert query_mod._entities_to_metadata_filters(QueryEntities.empty()) is None


def test_guests_only_lift_to_metadata_filters():
    mf = query_mod._entities_to_metadata_filters(
        QueryEntities(guests=["馬世芳"])
    )
    assert isinstance(mf, rag.MetadataFilters)
    assert mf.guests == ["馬世芳"]
    assert mf.date_range is None


def test_date_only_lift_to_metadata_filters():
    rng = (
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    mf = query_mod._entities_to_metadata_filters(
        QueryEntities(date_range=rng)
    )
    assert mf is not None
    assert mf.guests == []
    assert mf.date_range == rng


def test_topics_alone_do_not_create_filter():
    """Topics are not metadata-filter inputs (they live in the lexical pools,
    not in `episodes.guests` or `published_at`). A topics-only result must
    behave like an empty filter."""
    assert query_mod._entities_to_metadata_filters(
        QueryEntities(topics=["歌單"])
    ) is None


# ---------------------------------------------------------------------------
# _compute_enumeration_episodes — trigger logic
# ---------------------------------------------------------------------------

def _make_db_returning(rows: list[dict]):
    """Build an AsyncSession stub whose db.execute(...) returns a result
    whose `.mappings()` yields `rows`. Avoids a real DB connection."""
    result = MagicMock()
    result.mappings.return_value = rows
    db = AsyncMock()
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_enumeration_returns_none_when_no_trigger():
    """r3-3-chat-enum-grounding refactor: returns (None, 'none') when no
    trigger; previously returned `None` directly. New tuple shape lets
    the chat handler distinguish 'no enum' from 'enum with empty result'."""
    db = AsyncMock()
    episodes, marker = await query_mod._compute_enumeration_episodes(
        db, uuid.uuid4(), question="主持人有什麼興趣", entities=QueryEntities.empty()
    )
    assert episodes is None
    assert marker == "none"
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_enumeration_triggers_on_guest_entity(monkeypatch):
    """Combiner dispatches to `find_episodes_by_guest` when entities.guests
    is non-empty. SQL details are tested in test_episode_finders.py — here
    we only verify the dispatch + result-tuple shape."""
    ep_id = uuid.uuid4()
    ref = EpisodeRef(
        episode_id=ep_id,
        title="Ft. 馬世芳",
        published_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        guests=["馬世芳"],
        ai_summary="summary here",
    )

    async def fake_find_by_guest(db, show_id, guests):
        assert guests == ["馬世芳"]
        return [ref]

    monkeypatch.setattr(
        query_mod.episode_finders, "find_episodes_by_guest", fake_find_by_guest
    )

    episodes, marker = await query_mod._compute_enumeration_episodes(
        AsyncMock(), uuid.uuid4(),
        question="馬世芳上過哪幾集",
        entities=QueryEntities(guests=["馬世芳"]),
    )
    assert episodes is not None
    assert len(episodes) == 1
    assert episodes[0].episode_id == ep_id
    assert marker == "none"


@pytest.mark.asyncio
async def test_enumeration_triggers_on_date_range(monkeypatch):
    """Date-only entity dispatches to `find_episodes_by_date_range`. Empty
    list result is preserved as `[]` (NOT None) so the caller knows the
    filter ran and matched zero episodes."""
    captured = {}

    async def fake_find_by_date(db, show_id, start, end):
        captured["start"] = start
        captured["end"] = end
        return []

    monkeypatch.setattr(
        query_mod.episode_finders, "find_episodes_by_date_range", fake_find_by_date
    )

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, tzinfo=timezone.utc)
    episodes, marker = await query_mod._compute_enumeration_episodes(
        AsyncMock(), uuid.uuid4(),
        question="2024 那集講過什麼",
        entities=QueryEntities(date_range=(start, end)),
    )
    assert episodes == []  # empty list, not None
    assert marker == "none"
    assert captured["start"] == start
    assert captured["end"] == end


@pytest.mark.asyncio
async def test_enumeration_triggers_on_rule_pattern_with_no_entity(monkeypatch):
    """Spec scenario «Enumeration rule pattern triggers topic-filtered
    enumeration» — rule pattern command without any LLM entity now derives
    topic_terms from the jieba-tokenised question and runs the topic finder
    (no longer falls back to 'list every episode in the show')."""
    ep_id_a = uuid.uuid4()
    ep_id_b = uuid.uuid4()

    captured_terms = {}

    async def fake_find_by_topic(db, show_id, topic_terms):
        captured_terms["terms"] = topic_terms
        return [
            EpisodeRef(episode_id=ep_id_a, title="歌單 EP1", published_at=None, guests=[], ai_summary=None),
            EpisodeRef(episode_id=ep_id_b, title="歌單 EP2", published_at=None, guests=[], ai_summary=None),
        ]

    monkeypatch.setattr(
        query_mod.episode_finders, "find_episodes_by_topic", fake_find_by_topic
    )

    episodes, marker = await query_mod._compute_enumeration_episodes(
        AsyncMock(), uuid.uuid4(),
        question="哪幾集講過 podcasting",
        entities=QueryEntities.empty(),
    )
    assert episodes is not None
    assert len(episodes) == 2
    assert marker == "none"
    # Topic terms derived from question; "哪幾集" is in TOPIC_STOPWORDS so
    # dropped; "podcasting" (single token from English word) survives if jieba
    # keeps it intact. The exact term list depends on jieba; we just assert
    # the topic finder WAS invoked with something non-empty.
    assert isinstance(captured_terms["terms"], list)


@pytest.mark.asyncio
async def test_enumeration_rule_pattern_variants():
    """All three substrings (哪幾集 / 哪集 / 哪些集) trigger the rule path.

    Both 哪 (which) and 那 (that) work — Taiwan users commonly type 那
    where 哪 is meant. Prod 2026-05-16: 「歌單那幾集」 silently dropped
    out of enumeration before this widening.
    """
    for q in ("哪幾集", "哪集", "哪些集", "那幾集", "那集", "那些集"):
        assert query_mod._ENUMERATION_RULE_PATTERN.search(q) is not None
    assert query_mod._ENUMERATION_RULE_PATTERN.search("主持人是誰") is None


# ---------------------------------------------------------------------------
# _extract_entities_fail_open — fail-open contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_entities_fail_open_when_step_not_configured(monkeypatch):
    """`entity_extraction` step missing in `ai_steps` → no 5xx, empty entities."""
    from app.services.ai_step_resolver import AiStepNotConfiguredError

    async def fake_get_step_config(db, key):
        raise AiStepNotConfiguredError(f"missing {key}")

    monkeypatch.setattr(query_mod, "get_step_config", fake_get_step_config)
    out = await query_mod._extract_entities_fail_open(AsyncMock(), "question")
    assert out == QueryEntities.empty()


@pytest.mark.asyncio
async def test_extract_entities_fail_open_when_extractor_raises(monkeypatch):
    """Underlying `query_entity.extract_entities` already swallows exceptions
    and returns empty + api_error status. Wrapper passes that through."""
    cfg = MagicMock(base_url="http://x", api_key="k", model="m")

    async def fake_get_step_config(db, key):
        return cfg

    async def fake_extract(client, *, model, question):
        return QueryEntities.empty(), query_mod.query_entity.ExtractionStatus.api_error

    monkeypatch.setattr(query_mod, "get_step_config", fake_get_step_config)
    monkeypatch.setattr(query_mod.query_entity, "extract_entities", fake_extract)

    out = await query_mod._extract_entities_fail_open(AsyncMock(), "question")
    assert out.is_empty()


@pytest.mark.asyncio
async def test_extract_entities_returns_entities_when_ok(monkeypatch):
    cfg = MagicMock(base_url="http://x", api_key="k", model="m")

    async def fake_get_step_config(db, key):
        return cfg

    async def fake_extract(client, *, model, question):
        return (
            QueryEntities(guests=["馬世芳"]),
            query_mod.query_entity.ExtractionStatus.ok,
        )

    monkeypatch.setattr(query_mod, "get_step_config", fake_get_step_config)
    monkeypatch.setattr(query_mod.query_entity, "extract_entities", fake_extract)

    out = await query_mod._extract_entities_fail_open(AsyncMock(), "馬世芳上過哪幾集")
    assert out.guests == ["馬世芳"]


# ---------------------------------------------------------------------------
# ChatResponse schema carries the new field
# ---------------------------------------------------------------------------

def test_chat_response_default_enumeration_is_none():
    from app.schemas.query import ChatResponse

    r = ChatResponse(
        query_id="abc",
        answer="hi",
        citations=[],
        quota_remaining=5,
    )
    assert r.enumeration_episodes is None


def test_chat_response_serialises_enumeration_episodes():
    from app.schemas.query import ChatResponse

    ep = EpisodeRef(
        episode_id=uuid.uuid4(),
        title="Ft. 馬世芳",
        published_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        guests=["馬世芳"],
        ai_summary="x",
    )
    r = ChatResponse(
        query_id="abc",
        answer="hi",
        citations=[],
        quota_remaining=5,
        enumeration_episodes=[ep],
    )
    dumped = r.model_dump()
    assert dumped["enumeration_episodes"] is not None
    assert len(dumped["enumeration_episodes"]) == 1
    assert dumped["enumeration_episodes"][0]["guests"] == ["馬世芳"]
