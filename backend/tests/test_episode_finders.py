"""Unit tests for episode_finders.py — the tool-like SQL functions that
the chat-enum-grounding combiner dispatches to.

Coverage:
- TOPIC_STOPWORDS strips generic tokens from question-derived terms
- find_episodes_by_guest binds jsonb @> containment
- find_episodes_by_topic hits description_chunks tsvector (NOT transcript)
- find_episodes_by_date_range uses BETWEEN
- Empty input is a no-op (no DB call) for all three finders
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import episode_finders, tokenizer


# ---------------------------------------------------------------------------
# TOPIC_STOPWORDS + extract_topic_terms_from_question
# ---------------------------------------------------------------------------

def test_topic_stopwords_set_contains_starter_terms():
    """Sanity that the starter set covers the categories the design names."""
    for term in ("節目", "podcast", "Podcast", "哪幾集", "那幾集", "主持人", "的"):
        assert term in episode_finders.TOPIC_STOPWORDS


def test_extract_topic_terms_drops_length_1_tokens():
    tokenizer.reset_for_tests()
    # 「歌單」(2-char, real topic) survives; 「過」(1-char, particle) dropped
    out = episode_finders.extract_topic_terms_from_question("歌單講過")
    assert "歌單" in out
    assert "過" not in out
    for t in out:
        assert len(t) >= 2


def test_extract_topic_terms_drops_stopwords():
    """Spec scenario «TOPIC_STOPWORDS strips generic tokens» — input
    `節目裡的歌單哪幾集講過` should produce topic terms that exclude
    `節目`, `的`, `哪幾集`."""
    tokenizer.reset_for_tests()
    out = episode_finders.extract_topic_terms_from_question("節目裡的歌單哪幾集講過")
    assert "歌單" in out
    assert "節目" not in out
    assert "的" not in out
    assert "哪幾集" not in out


def test_extract_topic_terms_empty_input_returns_empty():
    tokenizer.reset_for_tests()
    assert episode_finders.extract_topic_terms_from_question("") == []
    assert episode_finders.extract_topic_terms_from_question("   ") == []


def test_extract_topic_terms_dedupes_preserving_order():
    tokenizer.reset_for_tests()
    # Repeated token only appears once, first-occurrence order kept
    out = episode_finders.extract_topic_terms_from_question("歌單 高雄 歌單")
    seen_once = [t for t in out if out.count(t) == 1]
    assert seen_once == out  # no duplicates


# ---------------------------------------------------------------------------
# find_episodes_by_guest
# ---------------------------------------------------------------------------

def _mock_db_with_rows(rows: list[dict]):
    result = MagicMock()
    result.mappings.return_value = rows
    db = AsyncMock()
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
async def test_find_by_guest_empty_list_skips_db():
    db = AsyncMock()
    out = await episode_finders.find_episodes_by_guest(db, uuid.uuid4(), [])
    assert out == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_find_by_guest_uses_jsonb_containment():
    """Spec scenario «find_episodes_by_guest uses jsonb containment»."""
    ep_id = uuid.uuid4()
    db = _mock_db_with_rows([{
        "id": ep_id, "title": "EP143", "published_at": None,
        "guests": ["馬世芳"], "ai_summary": None,
    }])
    out = await episode_finders.find_episodes_by_guest(db, uuid.uuid4(), ["馬世芳"])
    assert len(out) == 1
    assert out[0].episode_id == ep_id
    assert out[0].guests == ["馬世芳"]
    # Verify SQL shape + params
    call_args = db.execute.call_args
    sql_str = str(call_args[0][0])
    params = call_args[0][1]
    assert "guests @> CAST(:guests AS jsonb)" in sql_str
    # Param is JSON-encoded list (utf-8 escaped form acceptable too)
    import json as _json
    assert _json.loads(params["guests"]) == ["馬世芳"]


# ---------------------------------------------------------------------------
# find_episodes_by_topic
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_by_topic_empty_terms_skips_db():
    db = AsyncMock()
    out = await episode_finders.find_episodes_by_topic(db, uuid.uuid4(), [])
    assert out == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_find_by_topic_whitespace_only_terms_skips_db():
    db = AsyncMock()
    out = await episode_finders.find_episodes_by_topic(db, uuid.uuid4(), ["", "   "])
    assert out == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_find_by_topic_uses_description_chunks_tsvector():
    """Spec scenario «find_episodes_by_topic uses description_chunks
    tsvector» — SQL MUST JOIN episode_description_chunks and apply
    `text_tsvector @@ to_tsquery('simple', :tsquery_text)`."""
    db = _mock_db_with_rows([])
    await episode_finders.find_episodes_by_topic(db, uuid.uuid4(), ["歌單"])
    sql_str = str(db.execute.call_args[0][0])
    assert "episode_description_chunks" in sql_str
    assert "text_tsvector @@ to_tsquery('simple', :tsquery_text)" in sql_str


@pytest.mark.asyncio
async def test_find_by_topic_does_not_touch_transcript_chunks():
    """Title pool is weight 0.5 in retrieval but the enumeration finder
    deliberately ignores transcript-level matches — only the per-episode
    description tsvector is consulted to avoid noise."""
    db = _mock_db_with_rows([])
    await episode_finders.find_episodes_by_topic(db, uuid.uuid4(), ["歌單"])
    sql_str = str(db.execute.call_args[0][0])
    assert "transcript_chunks" not in sql_str


@pytest.mark.asyncio
async def test_find_by_topic_or_joins_multiple_terms():
    """Two topic terms should OR-join in the tsquery, not AND, so an
    episode that matches either term still surfaces."""
    db = _mock_db_with_rows([])
    await episode_finders.find_episodes_by_topic(db, uuid.uuid4(), ["歌單", "高雄"])
    params = db.execute.call_args[0][1]
    assert params["tsquery_text"] == "歌單 | 高雄"


@pytest.mark.asyncio
async def test_find_by_topic_jieba_splits_phrase():
    """enumeration-rule-pattern-broaden bugfix: a multi-character LLM topic
    phrase like "高雄美食" MUST be jieba-split into ["高雄", "美食"] before
    being OR-joined into the tsquery. Without this, Postgres simple
    analyzer keeps "高雄美食" as a single lexeme that never matches the
    jieba-tokenised description corpus."""
    tokenizer.reset_for_tests()
    db = _mock_db_with_rows([])
    await episode_finders.find_episodes_by_topic(db, uuid.uuid4(), ["高雄美食"])
    params = db.execute.call_args[0][1]
    assert params["tsquery_text"] == "高雄 | 美食"


@pytest.mark.asyncio
async def test_find_by_topic_all_stopword_term_falls_back_to_raw():
    """If jieba produces only stopword tokens for a term (e.g. the LLM
    surfaces "節目" which is in TOPIC_STOPWORDS), the finder MUST retain
    the raw term in the tsquery — silently dropping a term the LLM chose
    to surface erases signal. Fallback target: literal raw term."""
    tokenizer.reset_for_tests()
    db = _mock_db_with_rows([])
    await episode_finders.find_episodes_by_topic(db, uuid.uuid4(), ["節目"])
    params = db.execute.call_args[0][1]
    assert params["tsquery_text"] == "節目"


@pytest.mark.asyncio
async def test_find_by_topic_dedupes_across_terms():
    """When jieba splits two input terms that share a component (e.g.
    [高雄美食, 美食地圖] both produce 美食), the shared token MUST appear
    exactly once in the final OR list, with first-occurrence order
    preserved."""
    tokenizer.reset_for_tests()
    db = _mock_db_with_rows([])
    await episode_finders.find_episodes_by_topic(
        db, uuid.uuid4(), ["高雄美食", "美食地圖"]
    )
    params = db.execute.call_args[0][1]
    assert params["tsquery_text"] == "高雄 | 美食 | 地圖"


@pytest.mark.asyncio
async def test_find_episodes_by_topic_title_only_match():
    """enumeration-topic-finder-include-title: when an episode's title
    contains the topic term but none of its description chunks do, the
    finder MUST still return that episode. SQL-level assertion: the
    rewritten _TOPIC_SQL MUST include `title_tsvector @@ to_tsquery(...)`
    so the title pool is consulted; mock row assertion: when the DB
    returns such an episode it is packaged into the EpisodeRef list."""
    title_only_ep_id = uuid.uuid4()
    db = _mock_db_with_rows([{
        "id": title_only_ep_id,
        "title": "EP19｜在通往世界最強的路上，意外撿到的動漫歌單",
        "published_at": None,
        "guests": [],
        "ai_summary": None,
    }])
    out = await episode_finders.find_episodes_by_topic(
        db, uuid.uuid4(), ["歌單"]
    )
    sql_str = str(db.execute.call_args[0][0])
    # Title pool consulted in the new SQL
    assert "title_tsvector @@ to_tsquery('simple', :tsquery_text)" in sql_str
    # The title-only row is surfaced
    assert len(out) == 1
    assert out[0].episode_id == title_only_ep_id


@pytest.mark.asyncio
async def test_find_episodes_by_topic_description_only_match():
    """Regression guard for enumeration-topic-finder-include-title: an
    episode that previously matched via description chunks (title does
    not contain the term) MUST still be returned after the SQL rewrite.
    The new EXISTS clause MUST still query `episode_description_chunks`
    with the same tsquery."""
    desc_only_ep_id = uuid.uuid4()
    db = _mock_db_with_rows([{
        "id": desc_only_ep_id,
        "title": "EP140｜高雄美食第二彈",
        "published_at": None,
        "guests": [],
        "ai_summary": None,
    }])
    out = await episode_finders.find_episodes_by_topic(
        db, uuid.uuid4(), ["美食"]
    )
    sql_str = str(db.execute.call_args[0][0])
    # Description pool still consulted via EXISTS subquery
    assert "EXISTS" in sql_str
    assert "episode_description_chunks" in sql_str
    assert "d.text_tsvector @@ to_tsquery('simple', :tsquery_text)" in sql_str
    # The description-only row is surfaced
    assert len(out) == 1
    assert out[0].episode_id == desc_only_ep_id


@pytest.mark.asyncio
async def test_find_episodes_by_topic_both_match_dedup():
    """When an episode's title AND its description chunks both contain
    the topic term, the rewritten SQL MUST return the episode exactly
    once (distinct by `episodes.id`). The EXISTS-OR form is distinct by
    design (each `episodes` row evaluated once); this test pins that
    contract by asserting the SQL drives off `episodes` without joining
    description chunks (which would multiply rows on N matching chunks)
    and uses a top-level OR rather than UNION ALL."""
    both_ep_id = uuid.uuid4()
    # If DB-level dedup were broken, a JOIN against description_chunks
    # would surface N rows for N matching chunks. The EXISTS-OR form
    # ensures one row per episode regardless of chunk count, so the
    # mock returns one row to mirror that contract.
    db = _mock_db_with_rows([{
        "id": both_ep_id,
        "title": "EP143｜歌單之夜",
        "published_at": None,
        "guests": [],
        "ai_summary": None,
    }])
    out = await episode_finders.find_episodes_by_topic(
        db, uuid.uuid4(), ["歌單"]
    )
    sql_str = str(db.execute.call_args[0][0])
    # No JOIN on description_chunks (would multiply rows); only EXISTS
    assert "JOIN episode_description_chunks" not in sql_str
    # No UNION ALL (we picked EXISTS-OR per design Decision 1)
    assert "UNION ALL" not in sql_str
    # Episode surfaces exactly once
    assert len(out) == 1
    assert out[0].episode_id == both_ep_id


@pytest.mark.asyncio
async def test_find_by_topic_escapes_tsquery_operators():
    """Stray tsquery operators inside a LLM-extracted topic must not
    blow up to_tsquery — they are replaced with whitespace."""
    db = _mock_db_with_rows([])
    await episode_finders.find_episodes_by_topic(
        db, uuid.uuid4(), ["歌單&惡意", "高雄"]
    )
    params = db.execute.call_args[0][1]
    # The `&` operator inside the first term is stripped to whitespace
    # then the cleaned term joined with the second via ` | `
    assert "&" not in params["tsquery_text"]
    assert "高雄" in params["tsquery_text"]


# ---------------------------------------------------------------------------
# find_episodes_by_date_range
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_find_by_date_range_between_bound():
    """Spec scenario «find_episodes_by_date_range BETWEEN bound»."""
    db = _mock_db_with_rows([])
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    await episode_finders.find_episodes_by_date_range(
        db, uuid.uuid4(), start, end,
    )
    sql_str = str(db.execute.call_args[0][0])
    params = db.execute.call_args[0][1]
    assert "published_at BETWEEN :start AND :end" in sql_str
    assert params["start"] == start
    assert params["end"] == end
