"""API tests for EQ2e endpoints (asr-homophone-full-backfill).

Covers detect-existing (F6), backfill-status / backfill-cancel (F8), batch-restore
(F8), and approve apply_to_existing (F-approve). Celery enqueue / revoke is
monkeypatched so no broker is needed.

Specs: asr-homophone-detection, asr-correction-dictionary.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.asr_correction_term import AsrCorrectionTerm
from app.models.show import Show
from app.services import asr_correction


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def asr_show():
    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionFactory() as db:
        show = Show(title=f"eq2e-{suffix}", rss_url=f"https://e.com/{suffix}.rss")
        db.add(show)
        await db.commit()
        await db.refresh(show)
        sid = show.id

    yield {"show_id": sid, "suffix": suffix}

    from sqlalchemy import delete, or_

    async with AsyncSessionFactory() as db:
        await db.execute(
            delete(AsrCorrectionTerm).where(
                or_(
                    AsrCorrectionTerm.wrong.like(f"%{suffix}"),
                    AsrCorrectionTerm.show_id == sid,
                )
            )
        )
        await db.execute(delete(Show).where(Show.id == sid))
        await db.commit()


async def _seed_candidate(show_id, suffix) -> str:
    async with AsyncSessionFactory() as db:
        row = AsrCorrectionTerm(
            wrong=f"候選{suffix}",
            correct="正字",
            scope="show",
            show_id=show_id,
            enabled=False,
            source="llm",
            status="pending",
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return str(row.id)


# ─── F6: detect-existing ───────────────────────────────────────────────


async def test_detect_existing_dry_run_does_not_enqueue(
    client, auth_admin, asr_show, monkeypatch
):
    from app.workers.tasks import detect_existing_episodes

    called = {"n": 0}
    monkeypatch.setattr(
        detect_existing_episodes,
        "delay",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )

    r = await client.post(
        "/admin/asr-corrections/detect-existing",
        json={"show_id": str(asr_show["show_id"]), "dry_run": True},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["task_id"] is None
    assert "episode_count" in body and "estimated_cost_usd" in body
    assert called["n"] == 0, "dry-run must not enqueue a job"


async def test_detect_existing_real_run_enqueues(
    client, auth_admin, asr_show, monkeypatch
):
    from app.workers.tasks import detect_existing_episodes

    monkeypatch.setattr(
        detect_existing_episodes,
        "delay",
        lambda *a, **k: SimpleNamespace(id="detect-task-1"),
    )

    r = await client.post(
        "/admin/asr-corrections/detect-existing",
        json={"show_id": str(asr_show["show_id"]), "dry_run": False},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False
    assert body["task_id"] == "detect-task-1"


# ─── F8: backfill-status / backfill-cancel ─────────────────────────────


async def test_backfill_status_unknown_id_does_not_error(client, auth_admin):
    r = await client.get(
        f"/admin/asr-corrections/backfill-status/{uuid.uuid4()}",
        cookies=auth_admin["cookies"],
    )
    assert r.status_code == 200, r.text
    # an unknown / not-yet-started id maps to a known shape, never a 500
    assert r.json()["state"] in {"PENDING", "UNKNOWN"}


async def test_backfill_cancel_triggers_revoke(client, auth_admin, monkeypatch):
    from app.workers.celery_app import celery_app

    captured = {}
    monkeypatch.setattr(
        celery_app.control,
        "revoke",
        lambda task_id, **kw: captured.update({"task_id": task_id, **kw}),
    )

    tid = str(uuid.uuid4())
    r = await client.post(
        f"/admin/asr-corrections/backfill-cancel/{tid}",
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"task_id": tid, "revoked": True}
    assert captured["task_id"] == tid
    assert captured.get("terminate") is True


# ─── F8: batch-restore (endpoint wiring) ───────────────────────────────


async def test_batch_restore_endpoint_returns_report(
    client, auth_admin, asr_show, monkeypatch
):
    async def fake_batch_restore(db, *, show_id=None, embedding_cfg=None):
        return asr_correction.BackfillReport(
            affected_transcripts=2, affected_segments=4, affected_chunks=5,
            failed_chunk_ids=[],
        )

    monkeypatch.setattr(asr_correction, "batch_restore", fake_batch_restore)

    r = await client.post(
        "/admin/asr-corrections/batch-restore",
        json={"show_id": str(asr_show["show_id"])},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["affected_transcripts"] == 2
    assert body["dry_run"] is False


# ─── F-approve: approve apply_to_existing ──────────────────────────────


async def test_approve_apply_to_existing_enqueues(
    client, auth_admin, asr_show, monkeypatch
):
    from app.workers.tasks import backfill_asr_corrections

    captured = {}
    monkeypatch.setattr(
        backfill_asr_corrections,
        "delay",
        lambda **kw: captured.update(kw) or SimpleNamespace(id="apply-task-1"),
    )
    cid = await _seed_candidate(asr_show["show_id"], asr_show["suffix"])

    r = await client.post(
        f"/admin/asr-corrections/{cid}/approve",
        json={"apply_to_existing": True},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["enabled"] is True
    assert body["task_id"] == "apply-task-1"
    assert captured.get("term_id") == cid, "rule-application scoped to the term"


async def test_approve_without_flag_does_not_enqueue(
    client, auth_admin, asr_show, monkeypatch
):
    from app.workers.tasks import backfill_asr_corrections

    called = {"n": 0}
    monkeypatch.setattr(
        backfill_asr_corrections,
        "delay",
        lambda **kw: called.__setitem__("n", called["n"] + 1),
    )
    cid = await _seed_candidate(asr_show["show_id"], asr_show["suffix"])

    r = await client.post(
        f"/admin/asr-corrections/{cid}/approve",
        json={"apply_to_existing": False},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] is None
    assert called["n"] == 0


async def test_approve_no_body_does_not_enqueue(
    client, auth_admin, asr_show, monkeypatch
):
    from app.workers.tasks import backfill_asr_corrections

    called = {"n": 0}
    monkeypatch.setattr(
        backfill_asr_corrections,
        "delay",
        lambda **kw: called.__setitem__("n", called["n"] + 1),
    )
    cid = await _seed_candidate(asr_show["show_id"], asr_show["suffix"])

    r = await client.post(
        f"/admin/asr-corrections/{cid}/approve",
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["task_id"] is None
    assert called["n"] == 0
