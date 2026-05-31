"""Endpoint tests for POST /shows/{show_id}/keyword-search + admin threshold.

Authenticated (auth_member) callers bypass the per-IP rate limit, so these
tests do not require Redis. Integration tests that touch the DB skip when no
local Postgres is reachable.
"""
from __future__ import annotations

import secrets
import uuid

import jieba
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func

from app.services import keyword_search, tokenizer
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)

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
    return func.to_tsvector("simple", " ".join(tokenizer.tokenize(text_value)))


@pytest_asyncio.fixture
async def show_factory(db_session):
    from app.models.show import Show

    created: list = []

    async def _make() -> "Show":
        suffix = secrets.token_hex(4)
        show = Show(
            title=f"pytest-kw-ep-show-{suffix}",
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


async def _seed_episode_with_chunks(db, show_id, title, chunk_texts):
    from app.models.episode import Episode
    from app.models.transcript import Transcript, TranscriptStatus
    from app.models.transcript_chunk import TranscriptChunk

    suffix = secrets.token_hex(4)
    ep = Episode(
        show_id=show_id,
        title=title,
        audio_url=f"https://example.test/{suffix}.mp3",
        guid=f"pytest-kw-ep-{suffix}",
        title_tsvector=_tsv(title),
    )
    db.add(ep)
    await db.commit()
    await db.refresh(ep)

    tr = Transcript(episode_id=ep.id, status=TranscriptStatus.completed)
    db.add(tr)
    await db.commit()
    await db.refresh(tr)

    for i, txt in enumerate(chunk_texts):
        db.add(
            TranscriptChunk(
                transcript_id=tr.id,
                chunk_index=i,
                start_time=float(i * 10),
                end_time=float(i * 10 + 9),
                text=txt,
                text_tsvector=_tsv(txt),
                segment_ids=[uuid.uuid4()],
            )
        )
    await db.commit()
    return ep


def _client(auth):
    """AsyncClient carrying the auth cookies + CSRF/Origin headers.

    Authenticated POSTs must clear the CSRF + Origin middleware, so the derived
    CSRF token and Origin from the auth fixture are sent on every request.
    """
    return AsyncClient(
        transport=ASGITransport(app=_app()),
        base_url="http://test",
        cookies=auth["cookies"],
        headers=auth["csrf_headers"],
    )


def _app():
    from app.main import app

    return app


# ─── 3.3 route registered ───


def test_route_registered():
    app = _app()
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/shows/{show_id}/keyword-search" in paths


# ─── 3.2 endpoint contract ───


@db_required
@pytest.mark.asyncio
async def test_keyword_search_404_unknown_show(auth_member):
    async with _client(auth_member) as client:
        resp = await client.post(
            f"/shows/{uuid.uuid4()}/keyword-search", json={"query": TERM_A}
        )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "SHOW_NOT_FOUND"


@db_required
@pytest.mark.asyncio
async def test_keyword_search_422_empty_query(auth_member, show_factory):
    show = await show_factory()
    async with _client(auth_member) as client:
        resp = await client.post(
            f"/shows/{show.id}/keyword-search", json={"query": "！！！"}
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "EMPTY_QUERY"


@db_required
@pytest.mark.asyncio
async def test_keyword_search_200_valid(auth_member, show_factory, db_session):
    show = await show_factory()
    await _seed_episode_with_chunks(
        db_session,
        show.id,
        "valid ep",
        [f"今天聊到 {TERM_A} 還有 {TERM_B} 的故事"],
    )
    async with _client(auth_member) as client:
        resp = await client.post(
            f"/shows/{show.id}/keyword-search",
            json={"query": f"{TERM_A} {TERM_B}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "keyword"
    assert body["terms"] == [TERM_A, TERM_B]
    assert body["t1"]["total"] >= 1


# ─── 3.4 pagination contract ───


@db_required
@pytest.mark.asyncio
async def test_pagination_contract(auth_member, show_factory, db_session):
    show = await show_factory()
    texts = [f"{TERM_A} 與 {TERM_B} 第 {i} 段內容" for i in range(12)]
    await _seed_episode_with_chunks(db_session, show.id, "pagination ep", texts)

    async def _page(offset):
        async with _client(auth_member) as client:
            resp = await client.post(
                f"/shows/{show.id}/keyword-search",
                json={"query": f"{TERM_A} {TERM_B}", "offset_t1": offset, "limit": 5},
            )
        return resp.json()

    p0, p5, p10 = await _page(0), await _page(5), await _page(10)
    assert len(p0["t1"]["items"]) == 5
    assert len(p5["t1"]["items"]) == 5
    assert len(p10["t1"]["items"]) == 2
    assert p0["t1"]["total"] == p5["t1"]["total"] == p10["t1"]["total"] == 12


# ─── 4.1 admin threshold round-trip ───


@db_required
@pytest.mark.asyncio
async def test_admin_threshold_roundtrip_and_collapse(
    auth_admin, show_factory, db_session, monkeypatch
):
    # PUT publishes max_concurrent to Redis; stub it out (Redis down locally).
    monkeypatch.setattr(
        "app.api.settings.publish_max_concurrent", lambda *_a, **_k: None
    )

    async with _client(auth_admin) as client:
        # Establish a deterministic baseline (the singleton row persists across
        # test runs, so we can't assume the migration default is still in place).
        baseline = await client.put(
            "/admin/settings", json={"keyword_t2_collapse_threshold": 10}
        )
        assert baseline.status_code == 200

        got = await client.get("/admin/settings")
        assert got.status_code == 200
        assert got.json()["keyword_t2_collapse_threshold"] == 10

        put = await client.put(
            "/admin/settings",
            json={"keyword_t2_collapse_threshold": 3},
        )
        assert put.status_code == 200
        assert put.json()["keyword_t2_collapse_threshold"] == 3

        got2 = await client.get("/admin/settings")
        assert got2.json()["keyword_t2_collapse_threshold"] == 3

    # 5 matching chunks → t1.total = 5 >= threshold 3 → t2 collapsed.
    show = await show_factory()
    texts = [f"{TERM_A} 與 {TERM_B} 段 {i}" for i in range(5)]
    await _seed_episode_with_chunks(db_session, show.id, "collapse ep", texts)

    async with _client(auth_admin) as client:
        resp = await client.post(
            f"/shows/{show.id}/keyword-search",
            json={"query": f"{TERM_A} {TERM_B}"},
        )
    body = resp.json()
    assert body["t1"]["total"] == 5
    assert body["t2"]["collapsed"] is True

    # restore threshold to default so other tests/state are unaffected
    async with _client(auth_admin) as client:
        await client.put(
            "/admin/settings",
            json={"keyword_t2_collapse_threshold": 10},
        )


# ─── 5.1 timeout maps to 503 at the endpoint ───


@db_required
@pytest.mark.asyncio
async def test_endpoint_timeout_returns_503(auth_member, show_factory, monkeypatch):
    show = await show_factory()

    async def slow_t1(*a, **k):
        import asyncio

        await asyncio.sleep(0.5)
        return ([], 0)

    monkeypatch.setattr(keyword_search, "QUERY_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(keyword_search, "query_t1", slow_t1)

    async with _client(auth_member) as client:
        resp = await client.post(
            f"/shows/{show.id}/keyword-search",
            json={"query": f"{TERM_A} {TERM_B}"},
        )
    assert resp.status_code == 503
    assert resp.json()["detail"]["error_code"] == "KEYWORD_SEARCH_TIMEOUT"
