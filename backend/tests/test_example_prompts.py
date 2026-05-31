"""Tests for change `per-show-mode-example-prompts`.

Covers: generation (materials → per-mode rows; insufficient → skip; re-run
replaces), the public GET endpoint, the admin backfill endpoint, and the
summary-pipeline chain enqueue. LLM calls are stubbed.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.episode import AiSummaryStatus, Episode
from app.models.show import Show
from app.models.show_example_prompt import ExamplePromptMode, ShowExamplePrompt

from .conftest import _postgres_reachable

pytestmark = pytest.mark.skipif(
    not _postgres_reachable(), reason="postgres not reachable"
)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


async def _seed_show(*, with_materials: bool, summaries_done: bool = True) -> uuid.UUID:
    async with AsyncSessionFactory() as db:
        show = Show(
            title="範例題測試節目",
            rss_url=f"https://example.com/rss/{uuid.uuid4()}",
            language="zh-tw",
        )
        db.add(show)
        await db.flush()
        status = (
            AiSummaryStatus.done.value if summaries_done else AiSummaryStatus.pending.value
        )
        for i in range(2):
            ep = Episode(
                show_id=show.id,
                title=f"EP{i} 測試集",
                audio_url=f"https://example.com/a/{i}.mp3",
                guid=f"guid-{show.id}-{i}",
                guests=["馬世芳", "迪拉胖"] if with_materials else [],
                ai_summary=("本集聊到獨立樂團與做音樂的理念。" if with_materials else None),
                ai_summary_status=status if with_materials else AiSummaryStatus.pending.value,
                ai_summary_generated_at=datetime.now(timezone.utc) if with_materials else None,
            )
            db.add(ep)
        await db.commit()
        return show.id


async def _cleanup(show_id: uuid.UUID):
    async with AsyncSessionFactory() as db:
        await db.execute(delete(Show).where(Show.id == show_id))
        await db.commit()


def _stub_llm(monkeypatch, *, lines="範例一\n範例二\n範例三"):
    """Stub get_step_config + _call_chat in the example_prompts service."""
    import app.services.example_prompts as ep

    async def fake_cfg(db, step_key):
        return SimpleNamespace(base_url="http://stub", api_key="stub", model="stub-model")

    async def fake_call(client, *, model, prompt):
        return lines

    monkeypatch.setattr(ep, "get_step_config", fake_cfg)
    monkeypatch.setattr(ep, "_call_chat", fake_call)


async def _count_by_mode(show_id):
    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(
                select(ShowExamplePrompt.mode, func.count())
                .where(ShowExamplePrompt.show_id == show_id)
                .group_by(ShowExamplePrompt.mode)
            )
        ).all()
    return {m.value if hasattr(m, "value") else m: c for m, c in rows}


# ── Task 2.2: generation ──────────────────────────────────────────────────

async def test_generate_writes_per_mode(monkeypatch):
    from app.services.example_prompts import generate_for_show

    _stub_llm(monkeypatch)
    show_id = await _seed_show(with_materials=True)
    try:
        async with AsyncSessionFactory() as db:
            counts = await generate_for_show(db, show_id)
        assert counts["index"] >= 1 and counts["semantic"] >= 1 and counts["chat"] >= 1
        by_mode = await _count_by_mode(show_id)
        for m in ("index", "semantic", "chat"):
            assert by_mode.get(m, 0) >= 1
    finally:
        await _cleanup(show_id)


async def test_insufficient_materials_skips(monkeypatch):
    from app.services.example_prompts import generate_for_show

    _stub_llm(monkeypatch)
    show_id = await _seed_show(with_materials=False)
    try:
        async with AsyncSessionFactory() as db:
            counts = await generate_for_show(db, show_id)  # must not raise
        assert counts == {"index": 0, "semantic": 0, "chat": 0}
        by_mode = await _count_by_mode(show_id)
        assert by_mode == {}
    finally:
        await _cleanup(show_id)


async def test_rerun_replaces_not_duplicates(monkeypatch):
    from app.services.example_prompts import generate_for_show

    _stub_llm(monkeypatch)
    show_id = await _seed_show(with_materials=True)
    try:
        async with AsyncSessionFactory() as db:
            await generate_for_show(db, show_id)
        first = await _count_by_mode(show_id)
        async with AsyncSessionFactory() as db:
            await generate_for_show(db, show_id)
        second = await _count_by_mode(show_id)
        assert first == second  # delete-then-insert → no growth
    finally:
        await _cleanup(show_id)


# ── Task 3.1: GET endpoint ────────────────────────────────────────────────

async def test_get_endpoint_per_mode(monkeypatch, client):
    from app.services.example_prompts import generate_for_show

    _stub_llm(monkeypatch, lines="甲\n乙\n丙")
    show_id = await _seed_show(with_materials=True)
    try:
        async with AsyncSessionFactory() as db:
            await generate_for_show(db, show_id)
        resp = await client.get(f"/shows/{show_id}/example-prompts")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"index", "semantic", "chat"}
        for m in ("index", "semantic", "chat"):
            assert body[m] == ["甲", "乙", "丙"]  # ordinal order
    finally:
        await _cleanup(show_id)


async def test_get_ungenerated_returns_empty_no_llm(monkeypatch, client):
    import app.services.example_prompts as ep

    def boom(*a, **k):
        raise AssertionError("read path must not invoke the LLM")

    monkeypatch.setattr(ep, "_call_chat", boom)
    show_id = await _seed_show(with_materials=True)  # has materials but never generated
    try:
        resp = await client.get(f"/shows/{show_id}/example-prompts")
        assert resp.status_code == 200
        assert resp.json() == {"index": [], "semantic": [], "chat": []}
    finally:
        await _cleanup(show_id)


# ── Task 3.2: admin backfill ──────────────────────────────────────────────

async def test_admin_backfill_one(monkeypatch, client, auth_admin):
    _stub_llm(monkeypatch)
    show_id = await _seed_show(with_materials=True)
    try:
        resp = await client.post(
            f"/admin/shows/{show_id}/example-prompts/backfill",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
        assert resp.status_code == 200, resp.text
        by_mode = await _count_by_mode(show_id)
        assert all(by_mode.get(m, 0) >= 1 for m in ("index", "semantic", "chat"))
    finally:
        await _cleanup(show_id)


async def test_admin_backfill_requires_admin(client):
    show_id = await _seed_show(with_materials=True)
    try:
        resp = await client.post(
            f"/admin/shows/{show_id}/example-prompts/backfill"
        )
        assert resp.status_code in (401, 403)
    finally:
        await _cleanup(show_id)


# ── Task 4.1: chain enqueue ───────────────────────────────────────────────

async def test_chain_enqueues_when_summaries_complete(monkeypatch):
    import app.workers.example_prompts_task as ept

    calls = []
    monkeypatch.setattr(
        ept.generate_show_example_prompts, "delay", lambda *a, **k: calls.append(a)
    )
    show_id = await _seed_show(with_materials=True, summaries_done=True)
    try:
        async with AsyncSessionFactory() as db:
            enqueued = await ept.maybe_enqueue_for_show(db, show_id)
        assert enqueued is True
        assert len(calls) == 1 and calls[0][0] == str(show_id)
    finally:
        await _cleanup(show_id)


async def test_chain_skips_when_summary_pending(monkeypatch):
    import app.workers.example_prompts_task as ept

    calls = []
    monkeypatch.setattr(
        ept.generate_show_example_prompts, "delay", lambda *a, **k: calls.append(a)
    )
    show_id = await _seed_show(with_materials=True, summaries_done=False)
    try:
        async with AsyncSessionFactory() as db:
            enqueued = await ept.maybe_enqueue_for_show(db, show_id)
        assert enqueued is False
        assert calls == []
    finally:
        await _cleanup(show_id)
