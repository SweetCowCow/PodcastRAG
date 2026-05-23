"""Unit tests for `find_episodes_by_recency` and the `find_episodes_by_date_range`
sort/limit kwargs (agentic-prompt-grounding-and-ordinal-tool change).

Pattern matches `test_episode_finders.py` — AsyncMock-based; we verify
SQL shape + bound params rather than running real seeded rows. Pydantic
validation tests are pure model tests with no DB.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.services import episode_finders, tokenizer
from app.services.chat_agent.tools import ListEpisodesInput


def _mock_db(rows: list[dict] | None = None, count: int = 0):
    """AsyncMock returning `rows` on first execute and `count` on second
    (find_episodes_by_recency issues two queries: SELECT + COUNT)."""
    select_result = MagicMock()
    select_result.mappings.return_value = rows or []
    count_result = MagicMock()
    count_result.scalar.return_value = count
    db = AsyncMock()
    db.execute.side_effect = [select_result, count_result]
    return db


def _mock_db_select_only(rows: list[dict] | None = None):
    """For find_episodes_by_date_range (single SELECT)."""
    result = MagicMock()
    result.mappings.return_value = rows or []
    db = AsyncMock()
    db.execute.return_value = result
    return db


# ---------------------------------------------------------------------------
# find_episodes_by_recency — SQL shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_n_newest_order():
    """Default order='newest', n=3 → DESC + LIMIT 3 + COUNT report."""
    show_id = uuid.uuid4()
    rows = [
        {"id": uuid.uuid4(), "title": f"EP{i}", "published_at": datetime(2025, i, 1, tzinfo=timezone.utc),
         "guests": [], "ai_summary": None}
        for i in (5, 4, 3)
    ]
    db = _mock_db(rows=rows, count=5)
    out = await episode_finders.find_episodes_by_recency(db, show_id, n=3)
    assert out["n_total_matched"] == 5
    assert len(out["episodes"]) == 3
    select_sql = str(db.execute.call_args_list[0][0][0])
    assert "ORDER BY e.published_at DESC NULLS LAST" in select_sql
    assert "LIMIT :n" in select_sql
    params = db.execute.call_args_list[0][0][1]
    assert params["n"] == 3
    assert params["show_id"] == show_id


@pytest.mark.asyncio
async def test_order_oldest():
    """order='oldest' → ASC."""
    db = _mock_db(rows=[], count=0)
    await episode_finders.find_episodes_by_recency(db, uuid.uuid4(), n=2, order="oldest")
    select_sql = str(db.execute.call_args_list[0][0][0])
    assert "ORDER BY e.published_at ASC NULLS LAST" in select_sql


@pytest.mark.asyncio
async def test_topic_filter():
    """topic='AI' → adds tsquery EXISTS clause + tsquery_text param."""
    tokenizer.reset_for_tests()
    db = _mock_db(rows=[], count=3)
    await episode_finders.find_episodes_by_recency(db, uuid.uuid4(), topic="AI")
    select_sql = str(db.execute.call_args_list[0][0][0])
    assert "episode_description_chunks" in select_sql
    assert "to_tsquery('simple', :tsquery_text)" in select_sql
    params = db.execute.call_args_list[0][0][1]
    assert "tsquery_text" in params
    assert params["tsquery_text"]


@pytest.mark.asyncio
async def test_year_range_single_year():
    """year_start=year_end=2024 → single-year AND clause."""
    db = _mock_db(rows=[], count=0)
    await episode_finders.find_episodes_by_recency(
        db, uuid.uuid4(), year_start=2024, year_end=2024
    )
    select_sql = str(db.execute.call_args_list[0][0][0])
    assert "EXTRACT(YEAR FROM e.published_at AT TIME ZONE 'Asia/Taipei')" in select_sql
    assert "BETWEEN :year_start AND :year_end" in select_sql
    params = db.execute.call_args_list[0][0][1]
    assert params["year_start"] == 2024
    assert params["year_end"] == 2024


@pytest.mark.asyncio
async def test_year_range_inclusive_both_ends():
    """year_start=2023, year_end=2024 → BETWEEN 2023 AND 2024 inclusive."""
    db = _mock_db(rows=[], count=0)
    await episode_finders.find_episodes_by_recency(
        db, uuid.uuid4(), year_start=2023, year_end=2024
    )
    params = db.execute.call_args_list[0][0][1]
    assert params["year_start"] == 2023
    assert params["year_end"] == 2024


@pytest.mark.asyncio
async def test_n_total_matched_reports_full_count():
    """n=3 with 8 total matching → n_returned=3 (limited) / n_total_matched=8."""
    rows = [
        {"id": uuid.uuid4(), "title": f"EP{i}", "published_at": datetime(2025, 1, i, tzinfo=timezone.utc),
         "guests": [], "ai_summary": None}
        for i in (1, 2, 3)
    ]
    db = _mock_db(rows=rows, count=8)
    out = await episode_finders.find_episodes_by_recency(db, uuid.uuid4(), n=3)
    assert len(out["episodes"]) == 3
    assert out["n_total_matched"] == 8


# ---------------------------------------------------------------------------
# ListEpisodesInput Pydantic validation
# ---------------------------------------------------------------------------

def test_n_validation_rejects_above_20():
    with pytest.raises(ValidationError):
        ListEpisodesInput(show_id=uuid.uuid4(), n=25)
    with pytest.raises(ValidationError):
        ListEpisodesInput(show_id=uuid.uuid4(), n=0)


def test_year_start_after_year_end_rejected():
    with pytest.raises(ValidationError):
        ListEpisodesInput(show_id=uuid.uuid4(), year_start=2025, year_end=2024)


# ---------------------------------------------------------------------------
# find_episodes_by_date_range — new order / limit kwargs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_date_range_with_limit_caps_results():
    """limit=2 → LIMIT :limit clause + bound param."""
    db = _mock_db_select_only(rows=[])
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 12, 31, tzinfo=timezone.utc)
    await episode_finders.find_episodes_by_date_range(
        db, uuid.uuid4(), start, end, limit=2
    )
    sql = str(db.execute.call_args[0][0])
    assert "LIMIT :limit" in sql
    assert "ORDER BY published_at DESC NULLS LAST" in sql
    params = db.execute.call_args[0][1]
    assert params["limit"] == 2


@pytest.mark.asyncio
async def test_date_range_order_oldest_reverses_sort():
    """order='oldest' → ASC."""
    db = _mock_db_select_only(rows=[])
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 12, 31, tzinfo=timezone.utc)
    await episode_finders.find_episodes_by_date_range(
        db, uuid.uuid4(), start, end, order="oldest", limit=2
    )
    sql = str(db.execute.call_args[0][0])
    assert "ORDER BY published_at ASC NULLS LAST" in sql


@pytest.mark.asyncio
async def test_date_range_backwards_compat_no_kwargs():
    """No kwargs → DESC + unbounded (no LIMIT)."""
    db = _mock_db_select_only(rows=[])
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 12, 31, tzinfo=timezone.utc)
    await episode_finders.find_episodes_by_date_range(db, uuid.uuid4(), start, end)
    sql = str(db.execute.call_args[0][0])
    assert "ORDER BY published_at DESC NULLS LAST" in sql
    assert "LIMIT" not in sql
    params = db.execute.call_args[0][1]
    assert "limit" not in params


@pytest.mark.asyncio
async def test_date_range_limit_zero_rejected():
    """limit=0 → ValueError at function entry."""
    db = _mock_db_select_only(rows=[])
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 12, 31, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        await episode_finders.find_episodes_by_date_range(
            db, uuid.uuid4(), start, end, limit=0
        )
