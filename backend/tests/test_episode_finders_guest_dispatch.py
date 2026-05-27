"""Unit tests for find_episodes_by_topic guest-index dispatch path
(b23-dataset-and-retrieval-rca-fix Phase 2).

Verifies the three spec scenarios:
- Two guest tokens trigger guest-index dispatch (in addition to tsquery path)
- Single guest token preserves prior behaviour (no guest SQL)
- No guest tokens preserve prior behaviour (no guest SQL)
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import episode_finders, tokenizer


def _row(ep_id: uuid.UUID, title: str, guests: list[str]) -> dict:
    return {
        "id": ep_id,
        "title": title,
        "published_at": None,
        "guests": guests,
        "ai_summary": None,
    }


def _mock_db_returning_rows_per_sql(
    *,
    known_guests: list[str],
    topic_rows: list[dict],
    guest_rows: list[dict],
) -> AsyncMock:
    """Build an AsyncMock db whose `execute()` returns different rows
    depending on which SQL is invoked. We dispatch by inspecting the
    SQL text passed to `db.execute(text(...), params)`.
    """
    db = AsyncMock()

    def make_result(rows: list[dict], known: list[str] | None = None):
        result = MagicMock()
        result.mappings.return_value = rows
        result.fetchall.return_value = [(n,) for n in (known or [])]
        return result

    async def execute(sql, params=None, *args, **kwargs):
        sql_text = str(sql)
        if "jsonb_array_elements_text" in sql_text:
            return make_result([], known=known_guests)
        if "guests ?| CAST" in sql_text:
            return make_result(guest_rows)
        return make_result(topic_rows)

    db.execute = AsyncMock(side_effect=execute)
    return db


@pytest.mark.asyncio
async def test_two_guest_tokens_trigger_guest_index_dispatch():
    """Spec scenario 1: ≥2 jieba tokens match known guests → guest SQL
    runs and its rows are unioned with topic-path rows."""
    tokenizer.reset_for_tests()
    ep_a = uuid.uuid4()
    ep_b = uuid.uuid4()
    # Show has known guests: Leo 王, 小老虎
    db = _mock_db_returning_rows_per_sql(
        known_guests=["Leo 王", "小老虎", "馬世芳"],
        topic_rows=[],  # title/description tsquery returns nothing
        guest_rows=[
            _row(ep_a, "EP107｜迪拉的男團夢", ["Leo 王"]),
            _row(ep_b, "EP116｜Ft. 小老虎、Leo 王", ["小老虎", "Leo 王"]),
        ],
    )
    # Clear LRU cache (per-process, may leak across tests)
    episode_finders._guest_name_cache.clear()
    eps, source = await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["Leo 王 小老虎"]
    )
    ids = {ep.episode_id for ep in eps}
    assert ep_a in ids
    assert ep_b in ids
    assert source == "guest_index"  # topic returned nothing, guest only


@pytest.mark.asyncio
async def test_single_guest_token_preserves_prior_behaviour():
    """Spec scenario 2: only one token matches known guests → guest SQL
    SHALL NOT run; returns topic-path result only."""
    tokenizer.reset_for_tests()
    ep_c = uuid.uuid4()
    db = _mock_db_returning_rows_per_sql(
        known_guests=["馬世芳"],
        topic_rows=[_row(ep_c, "EP143｜家常味", ["馬世芳"])],
        guest_rows=[],
    )
    episode_finders._guest_name_cache.clear()
    eps, source = await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["馬世芳的家常味"]
    )
    assert {ep.episode_id for ep in eps} == {ep_c}
    assert source == "topic_index"
    # Verify guest SQL was NOT called (only known-guests + topic SQL)
    sql_calls = [str(c[0][0]) for c in db.execute.call_args_list]
    assert not any("guests ?| CAST" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_no_guest_tokens_preserve_prior_behaviour():
    """Spec scenario 3: zero tokens match known guests → guest SQL
    SHALL NOT run."""
    tokenizer.reset_for_tests()
    ep_d = uuid.uuid4()
    db = _mock_db_returning_rows_per_sql(
        known_guests=["馬世芳", "Leo 王"],
        topic_rows=[_row(ep_d, "EP143｜家常味", [])],
        guest_rows=[],
    )
    episode_finders._guest_name_cache.clear()
    eps, source = await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["家常味"]
    )
    assert {ep.episode_id for ep in eps} == {ep_d}
    assert source == "topic_index"
    sql_calls = [str(c[0][0]) for c in db.execute.call_args_list]
    assert not any("guests ?| CAST" in s for s in sql_calls)


@pytest.mark.asyncio
async def test_backward_compat_wrapper_drops_source():
    """The original `find_episodes_by_topic(...) -> list[EpisodeRef]` shape
    must still work for existing callers (api/query.py, chat tool registry)."""
    tokenizer.reset_for_tests()
    db = _mock_db_returning_rows_per_sql(
        known_guests=[],
        topic_rows=[_row(uuid.uuid4(), "EP143", [])],
        guest_rows=[],
    )
    episode_finders._guest_name_cache.clear()
    eps = await episode_finders.find_episodes_by_topic(
        db, uuid.uuid4(), ["家常味"]
    )
    assert isinstance(eps, list)
    assert len(eps) == 1


@pytest.mark.asyncio
async def test_merged_source_when_both_paths_contribute():
    """When topic-path returns ≥1 row AND guest-path adds at least one
    new (non-overlap) episode, source SHALL be `merged`."""
    tokenizer.reset_for_tests()
    ep_topic = uuid.uuid4()
    ep_guest_only = uuid.uuid4()
    db = _mock_db_returning_rows_per_sql(
        known_guests=["Leo 王", "小老虎"],
        topic_rows=[_row(ep_topic, "EP143", [])],
        guest_rows=[_row(ep_guest_only, "EP116", ["小老虎", "Leo 王"])],
    )
    episode_finders._guest_name_cache.clear()
    eps, source = await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["Leo 王 小老虎"]
    )
    assert {ep.episode_id for ep in eps} == {ep_topic, ep_guest_only}
    assert source == "merged"
