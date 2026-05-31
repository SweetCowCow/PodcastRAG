"""Service-layer tests for keyword_search.

Integration tests (T1 / T2 / T3 / cap) need a local Postgres with pgvector +
tsvector and are skipped gracefully when one is not reachable. The orchestrator
gating and timeout tests are pure unit tests (query functions monkeypatched).
"""
from __future__ import annotations

import asyncio
import secrets

import jieba
import pytest
import pytest_asyncio
from sqlalchemy import delete, func

from app.services import keyword_search, tokenizer
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)

# Distinctive multi-char CJK terms the assertions depend on. Registered with
# jieba so both the seeded tsvectors and parse_query segment them identically.
TERM_A = "馬世芳"
TERM_B = "滅火器"


@pytest.fixture(autouse=True)
def _seeded_dict():
    tokenizer.reset_for_tests()
    for word in (TERM_A, TERM_B):
        jieba.add_word(word)
    tokenizer._loaded = True
    yield
    for word in (TERM_A, TERM_B):
        jieba.del_word(word)
    tokenizer.reset_for_tests()


def _tsv(text_value: str):
    """tsvector SQL expression mirroring the production rebuild pipeline."""
    return func.to_tsvector("simple", " ".join(tokenizer.tokenize(text_value)))


@pytest_asyncio.fixture
async def show_factory(db_session):
    from app.models.show import Show

    created: list = []

    async def _make() -> "Show":
        suffix = secrets.token_hex(4)
        show = Show(
            title=f"pytest-kw-show-{suffix}",
            rss_url=f"https://example.test/{suffix}.rss",
            language="zh",
        )
        db_session.add(show)
        await db_session.commit()
        await db_session.refresh(show)
        created.append(show.id)
        return show

    yield _make

    for sid in created:
        await db_session.execute(delete(Show).where(Show.id == sid))
    await db_session.commit()


async def _seed_episode(db, show_id, title: str):
    from app.models.episode import Episode

    suffix = secrets.token_hex(4)
    ep = Episode(
        show_id=show_id,
        title=title,
        audio_url=f"https://example.test/{suffix}.mp3",
        guid=f"pytest-kw-{suffix}",
        title_tsvector=_tsv(title),
    )
    db.add(ep)
    await db.commit()
    await db.refresh(ep)
    return ep


async def _seed_transcript(db, episode_id):
    from app.models.transcript import Transcript, TranscriptStatus

    tr = Transcript(episode_id=episode_id, status=TranscriptStatus.completed)
    db.add(tr)
    await db.commit()
    await db.refresh(tr)
    return tr


async def _add_chunk(db, transcript_id, idx: int, text_value: str):
    import uuid

    from app.models.transcript_chunk import TranscriptChunk

    db.add(
        TranscriptChunk(
            transcript_id=transcript_id,
            chunk_index=idx,
            start_time=float(idx * 10),
            end_time=float(idx * 10 + 9),
            text=text_value,
            text_tsvector=_tsv(text_value),
            segment_ids=[uuid.uuid4()],
        )
    )


async def _add_desc_chunk(db, episode_id, idx: int, text_value: str):
    from app.models.episode_description_chunk import EpisodeDescriptionChunk

    db.add(
        EpisodeDescriptionChunk(
            episode_id=episode_id,
            chunk_index=idx,
            text=text_value,
            text_tsvector=_tsv(text_value),
        )
    )


# ─── 2.1 query_t1: strict same-chunk AND ───


@db_required
@pytest.mark.asyncio
async def test_query_t1_strict_and(db_session, show_factory):
    show = await show_factory()
    ep = await _seed_episode(db_session, show.id, "T1 episode")
    tr = await _seed_transcript(db_session, ep.id)
    # 2 chunks contain BOTH terms; 1 chunk contains only TERM_A.
    await _add_chunk(db_session, tr.id, 0, f"今天聊到 {TERM_A} 還有 {TERM_B} 的故事")
    await _add_chunk(db_session, tr.id, 1, f"{TERM_B} 和 {TERM_A} 一起出現在這段")
    await _add_chunk(db_session, tr.id, 2, f"這段只提到 {TERM_A} 沒有別的")
    await db_session.commit()

    items, total = await keyword_search.query_t1(
        db_session, show.id, [TERM_A, TERM_B], offset=0, limit=25
    )
    assert total == 2
    assert len(items) == 2
    for it in items:
        assert TERM_A in it["text"] and TERM_B in it["text"]
        # hits carry per-term positions for both terms
        hit_terms = {h["term"] for h in it["hits"]}
        assert hit_terms == {TERM_A, TERM_B}


# ─── 2.2 query_t2: cross-pool episode AND ───


@db_required
@pytest.mark.asyncio
async def test_query_t2_cross_pool_and(db_session, show_factory):
    show = await show_factory()
    # Episode A: TERM_A only in title, TERM_B only in transcript → qualifies.
    ep_a = await _seed_episode(db_session, show.id, f"來賓 {TERM_A} 專訪")
    tr_a = await _seed_transcript(db_session, ep_a.id)
    await _add_chunk(db_session, tr_a.id, 0, f"他們現場演了 {TERM_B} 的歌")
    # Episode B: only TERM_A in title, TERM_B absent everywhere → excluded.
    ep_b = await _seed_episode(db_session, show.id, f"另一集 {TERM_A}")
    tr_b = await _seed_transcript(db_session, ep_b.id)
    await _add_chunk(db_session, tr_b.id, 0, "這集完全沒有第二個關鍵字")
    await db_session.commit()

    items, total = await keyword_search.query_t2(
        db_session, show.id, [TERM_A, TERM_B], offset=0, limit=25
    )
    assert total == 1
    assert len(items) == 1
    hit = items[0]
    assert hit["episode_id"] == ep_a.id
    assert hit["pool_counts"]["title"] >= 1
    assert hit["pool_counts"]["transcript"] >= 1


# ─── 2.3 query_t3: OR fallback ───


@db_required
@pytest.mark.asyncio
async def test_query_t3_or_fallback(db_session, show_factory):
    show = await show_factory()
    ep = await _seed_episode(db_session, show.id, "T3 episode")
    tr = await _seed_transcript(db_session, ep.id)
    # No single chunk has both terms — only OR can surface these.
    await _add_chunk(db_session, tr.id, 0, f"只有 {TERM_A} 在這段")
    await _add_chunk(db_session, tr.id, 1, f"只有 {TERM_B} 在那段")
    await db_session.commit()

    hits = await keyword_search.query_t3(db_session, show.id, [TERM_A, TERM_B])
    # OR semantics: both single-term chunks come back.
    assert len(hits) == 2
    texts = " ".join(h["text"] for h in hits)
    assert TERM_A in texts and TERM_B in texts


def test_build_tsquery_or_is_or_joined():
    # 2.3 contract: the fallback uses an OR-joined tsquery string.
    assert keyword_search.build_tsquery_or([TERM_A, TERM_B]) == f"{TERM_A} | {TERM_B}"


# ─── 2.4 orchestrator T3 gating (pure unit, monkeypatched) ───


@pytest.mark.asyncio
async def test_orchestrator_skips_t3_when_t1_has_hits(monkeypatch):
    calls = {"t3": 0}

    async def fake_t1(*a, **k):
        return ([{"chunk_id": "x"}], 3)

    async def fake_t2(*a, **k):
        return ([], 0)

    async def fake_t3(*a, **k):
        calls["t3"] += 1
        return []

    monkeypatch.setattr(keyword_search, "query_t1", fake_t1)
    monkeypatch.setattr(keyword_search, "query_t2", fake_t2)
    monkeypatch.setattr(keyword_search, "query_t3", fake_t3)

    resp = await keyword_search.run_keyword_search(
        None, "00000000-0000-0000-0000-000000000000", f"{TERM_A} {TERM_B}"
    )
    assert resp["t3"] is None
    assert calls["t3"] == 0
    assert resp["t1"]["total"] == 3


@pytest.mark.asyncio
async def test_orchestrator_runs_t3_when_t1_and_t2_empty(monkeypatch):
    calls = {"t3": 0}

    async def fake_empty(*a, **k):
        return ([], 0)

    async def fake_t3(*a, **k):
        calls["t3"] += 1
        return [{"chunk_id": "y"}]

    monkeypatch.setattr(keyword_search, "query_t1", fake_empty)
    monkeypatch.setattr(keyword_search, "query_t2", fake_empty)
    monkeypatch.setattr(keyword_search, "query_t3", fake_t3)

    resp = await keyword_search.run_keyword_search(
        None, "00000000-0000-0000-0000-000000000000", f"{TERM_A} {TERM_B}"
    )
    assert calls["t3"] == 1
    assert resp["t3"] is not None
    assert resp["t3"]["total"] == 1


@pytest.mark.asyncio
async def test_orchestrator_empty_query_raises(monkeypatch):
    with pytest.raises(keyword_search.EmptyKeywordQueryError):
        await keyword_search.run_keyword_search(
            None, "00000000-0000-0000-0000-000000000000", "！！！"
        )


# ─── 5.1 timeout maps to KeywordSearchTimeoutError ───


@pytest.mark.asyncio
async def test_run_keyword_search_timeout(monkeypatch):
    async def slow_t1(*a, **k):
        await asyncio.sleep(0.5)
        return ([], 0)

    monkeypatch.setattr(keyword_search, "QUERY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(keyword_search, "query_t1", slow_t1)

    with pytest.raises(keyword_search.KeywordSearchTimeoutError):
        await keyword_search.run_keyword_search(
            None, "00000000-0000-0000-0000-000000000000", f"{TERM_A} {TERM_B}"
        )


# ─── 5.2 T1 hard cap at 100 ───


@db_required
@pytest.mark.asyncio
async def test_t1_hard_cap_100(db_session, show_factory):
    show = await show_factory()
    ep = await _seed_episode(db_session, show.id, "cap episode")
    tr = await _seed_transcript(db_session, ep.id)
    # 250 chunks all match the AND query.
    for i in range(250):
        await _add_chunk(db_session, tr.id, i, f"{TERM_A} 與 {TERM_B} 第 {i} 段")
    await db_session.commit()

    items, total = await keyword_search.query_t1(
        db_session, show.id, [TERM_A, TERM_B], offset=95, limit=25
    )
    assert total == 100  # cap-aware total
    assert len(items) == 5  # cap 100 minus offset 95
