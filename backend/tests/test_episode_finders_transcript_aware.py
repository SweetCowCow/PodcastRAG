"""Unit tests for find_episodes_by_topic transcript-aware candidate source
(topic-prefilter-transcript-aware, b23).

Verifies the spec scenarios:
- A transcript-buried answer episode (title/desc silent) becomes a candidate
  when the topic has ≥2 discriminating tokens and the flag is on.
- The flag off path is bit-equivalent to the prior title/description behaviour
  (no transcript query runs).
- A single discriminating token does NOT trigger the transcript source.
- The transcript source is capped (the :cap param is bound).
- The discriminating-token gate removes show-name terms.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import episode_finders, tokenizer


def _row(ep_id: uuid.UUID, title: str, guests: list[str] | None = None) -> dict:
    return {
        "id": ep_id,
        "title": title,
        "published_at": None,
        "guests": guests or [],
        "ai_summary": None,
    }


def _mock_db_by_sql(
    *,
    known_guests: list[str] | None = None,
    topic_rows: list[dict] | None = None,
    guest_rows: list[dict] | None = None,
    transcript_rows: list[dict] | None = None,
) -> AsyncMock:
    """db.execute returns rows depending on which SQL is invoked, dispatched
    by inspecting the SQL text. Records nothing else."""
    db = AsyncMock()

    def make_result(rows: list[dict], known: list[str] | None = None):
        result = MagicMock()
        result.mappings.return_value = rows
        result.fetchall.return_value = [(n,) for n in (known or [])]
        return result

    async def execute(sql, params=None, *args, **kwargs):
        sql_text = str(sql)
        if "jsonb_array_elements_text" in sql_text:
            return make_result([], known=known_guests or [])
        if "guests ?| CAST" in sql_text:
            return make_result(guest_rows or [])
        if "transcript_chunks" in sql_text:
            return make_result(transcript_rows or [])
        return make_result(topic_rows or [])

    db.execute = AsyncMock(side_effect=execute)
    return db


def _transcript_sql_calls(db: AsyncMock) -> list:
    return [
        c
        for c in db.execute.call_args_list
        if "transcript_chunks" in str(c[0][0])
    ]


# ---------------------------------------------------------------------------
# Discriminating-token gate (Task 2.1)
# ---------------------------------------------------------------------------

def test_discriminating_tokens_excludes_show_name_terms(monkeypatch):
    monkeypatch.setattr(
        tokenizer, "get_show_name_terms", lambda: {"屌"}
    )
    out = episode_finders._discriminating_tokens(["迪拉", "Leo", "屌"])
    assert out == ["迪拉", "Leo"]


def test_discriminating_tokens_two_for_b23_topic(monkeypatch):
    """b23 topic "迪拉 Leo王" → ≥2 discriminating tokens (gate opens)."""
    monkeypatch.setattr(tokenizer, "get_show_name_terms", lambda: set())
    tokenizer.reset_for_tests()
    expanded = [
        tk
        for tk in tokenizer.tokenize("迪拉 Leo王")
        if len(tk) >= 2 and tk not in episode_finders.TOPIC_STOPWORDS
    ]
    assert len(episode_finders._discriminating_tokens(expanded)) >= 2


def test_discriminating_tokens_single_for_one_word_topic(monkeypatch):
    """A single-token topic like 歌單 → <2 (gate stays closed)."""
    monkeypatch.setattr(tokenizer, "get_show_name_terms", lambda: set())
    tokenizer.reset_for_tests()
    expanded = [
        tk
        for tk in tokenizer.tokenize("歌單")
        if len(tk) >= 2 and tk not in episode_finders.TOPIC_STOPWORDS
    ]
    assert len(episode_finders._discriminating_tokens(expanded)) < 2


# ---------------------------------------------------------------------------
# Transcript candidate source (Task 2.2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcript_buried_episode_becomes_candidate(monkeypatch):
    """Spec: ≥2 discriminating tokens + flag on → transcript-buried episode
    (title/desc silent, only transcript matches) is included."""
    monkeypatch.setattr(tokenizer, "get_show_name_terms", lambda: set())
    monkeypatch.setattr(
        episode_finders.settings, "enable_transcript_topic_prefilter", True
    )
    monkeypatch.setattr(
        episode_finders.settings, "enable_guest_dispatch", False
    )
    tokenizer.reset_for_tests()
    ep107 = uuid.uuid4()
    db = _mock_db_by_sql(
        topic_rows=[],  # title/desc silent
        transcript_rows=[_row(ep107, "EP107｜迪拉的男團夢")],
    )
    episode_finders._guest_name_cache.clear()
    eps, source = await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["迪拉 Leo王"]
    )
    assert ep107 in {ep.episode_id for ep in eps}
    assert source == "transcript_index"
    # The transcript query bound the cap param.
    ts_calls = _transcript_sql_calls(db)
    assert len(ts_calls) == 1
    assert "cap" in ts_calls[0][0][1]


@pytest.mark.asyncio
async def test_flag_off_skips_transcript_query(monkeypatch):
    """Spec: flag off → no transcript query; candidates = prior behaviour."""
    monkeypatch.setattr(tokenizer, "get_show_name_terms", lambda: set())
    monkeypatch.setattr(
        episode_finders.settings, "enable_transcript_topic_prefilter", False
    )
    monkeypatch.setattr(
        episode_finders.settings, "enable_guest_dispatch", False
    )
    tokenizer.reset_for_tests()
    ep_topic = uuid.uuid4()
    db = _mock_db_by_sql(
        topic_rows=[_row(ep_topic, "EP143")],
        transcript_rows=[_row(uuid.uuid4(), "EP107")],
    )
    episode_finders._guest_name_cache.clear()
    eps, source = await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["迪拉 Leo王"]
    )
    assert {ep.episode_id for ep in eps} == {ep_topic}
    assert source == "topic_index"
    assert _transcript_sql_calls(db) == []


@pytest.mark.asyncio
async def test_single_discriminating_token_skips_transcript_query(monkeypatch):
    """Spec: <2 discriminating tokens → transcript source NOT applied."""
    monkeypatch.setattr(tokenizer, "get_show_name_terms", lambda: set())
    monkeypatch.setattr(
        episode_finders.settings, "enable_transcript_topic_prefilter", True
    )
    monkeypatch.setattr(
        episode_finders.settings, "enable_guest_dispatch", False
    )
    tokenizer.reset_for_tests()
    ep_topic = uuid.uuid4()
    db = _mock_db_by_sql(
        topic_rows=[_row(ep_topic, "EP19｜歌單")],
        transcript_rows=[_row(uuid.uuid4(), "EP107")],
    )
    episode_finders._guest_name_cache.clear()
    eps, source = await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["歌單"]
    )
    assert {ep.episode_id for ep in eps} == {ep_topic}
    assert source == "topic_index"
    assert _transcript_sql_calls(db) == []


@pytest.mark.asyncio
async def test_transcript_query_runs_before_topic_sql(monkeypatch):
    """Topic SQL must remain the LAST db.execute call so existing tests that
    inspect call_args for topic-SQL shape keep working."""
    monkeypatch.setattr(tokenizer, "get_show_name_terms", lambda: set())
    monkeypatch.setattr(
        episode_finders.settings, "enable_transcript_topic_prefilter", True
    )
    monkeypatch.setattr(
        episode_finders.settings, "enable_guest_dispatch", False
    )
    tokenizer.reset_for_tests()
    db = _mock_db_by_sql(topic_rows=[], transcript_rows=[])
    episode_finders._guest_name_cache.clear()
    await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["迪拉 Leo王"]
    )
    last_sql = str(db.execute.call_args[0][0])
    assert "transcript_chunks" not in last_sql
    assert "title_tsvector" in last_sql


@pytest.mark.asyncio
async def test_topic_and_transcript_merge_source(monkeypatch):
    """topic + transcript both contribute distinct episodes → 'merged'."""
    monkeypatch.setattr(tokenizer, "get_show_name_terms", lambda: set())
    monkeypatch.setattr(
        episode_finders.settings, "enable_transcript_topic_prefilter", True
    )
    monkeypatch.setattr(
        episode_finders.settings, "enable_guest_dispatch", False
    )
    tokenizer.reset_for_tests()
    ep_topic = uuid.uuid4()
    ep_transcript = uuid.uuid4()
    db = _mock_db_by_sql(
        topic_rows=[_row(ep_topic, "EP144｜Ft. Leo王")],
        transcript_rows=[_row(ep_transcript, "EP107｜迪拉的男團夢")],
    )
    episode_finders._guest_name_cache.clear()
    eps, source = await episode_finders.find_episodes_by_topic_with_source(
        db, uuid.uuid4(), ["迪拉 Leo王"]
    )
    assert {ep.episode_id for ep in eps} == {ep_topic, ep_transcript}
    assert source == "merged"
