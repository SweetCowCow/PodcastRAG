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
