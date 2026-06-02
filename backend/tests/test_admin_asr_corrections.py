"""Tests for the admin ASR correction CRUD + backfill endpoints.

Spec: asr-correction-dictionary → Requirement "Correction rule CRUD API".
"""
from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.asr_correction_term import AsrCorrectionTerm
from app.models.show import Show


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def asr_show():
    """Seed one show; clean up the show + any rule created during the test."""
    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionFactory() as db:
        show = Show(title=f"asrapi-{suffix}", rss_url=f"https://e.com/{suffix}.rss")
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


async def test_endpoints_require_admin(client, auth_member, asr_show):
    suffix = asr_show["suffix"]
    r = await client.post(
        "/admin/asr-corrections",
        json={"wrong": f"x{suffix}", "correct": "y", "scope": "global"},
        cookies=auth_member["cookies"],
        headers=auth_member["csrf_headers"],
    )
    assert r.status_code == 403, r.text


async def test_create_show_rule_without_show_id_returns_422(
    client, auth_admin, asr_show
):
    suffix = asr_show["suffix"]
    r = await client.post(
        "/admin/asr-corrections",
        json={"wrong": f"a{suffix}", "correct": "b", "scope": "show"},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 422, r.text


async def test_crud_lifecycle(client, auth_admin, asr_show):
    suffix = asr_show["suffix"]
    # create global rule
    r = await client.post(
        "/admin/asr-corrections",
        json={"wrong": f"咪有企{suffix}", "correct": "滅火器", "scope": "global"},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 201, r.text
    rule = r.json()
    rid = rule["id"]
    assert rule["scope"] == "global"
    assert rule["enabled"] is True

    # list contains it
    r = await client.get(
        "/admin/asr-corrections", cookies=auth_admin["cookies"]
    )
    assert r.status_code == 200
    assert any(x["id"] == rid for x in r.json())

    # toggle enabled off
    r = await client.patch(
        f"/admin/asr-corrections/{rid}",
        json={"enabled": False},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False

    # delete
    r = await client.delete(
        f"/admin/asr-corrections/{rid}",
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 204, r.text


async def test_backfill_dry_run_returns_preview(client, auth_admin, asr_show):
    r = await client.post(
        "/admin/asr-corrections/backfill",
        json={"show_id": str(asr_show["show_id"]), "dry_run": True},
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["task_id"] is None
    assert "affected_chunks" in body and "estimated_cost_usd" in body


async def test_match_count_endpoint(client, auth_admin, asr_show):
    r = await client.get(
        f"/admin/asr-corrections/match-count?wrong=nonexistent{asr_show['suffix']}"
        "&scope=global",
        cookies=auth_admin["cookies"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["match_count"] == 0


# ─── asr-llm-homophone-postprocess (EQ2b): candidate review API ────────


async def _seed_candidate(show_id, suffix):
    """Insert a pending LLM candidate; return its id."""
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


async def test_review_endpoints_require_admin(client, auth_member, asr_show):
    cid = await _seed_candidate(asr_show["show_id"], asr_show["suffix"])
    r = await client.post(
        f"/admin/asr-corrections/{cid}/approve",
        cookies=auth_member["cookies"],
        headers=auth_member["csrf_headers"],
    )
    assert r.status_code == 403, r.text


async def test_list_filters_pending_llm_candidates(client, auth_admin, asr_show):
    await _seed_candidate(asr_show["show_id"], asr_show["suffix"])
    r = await client.get(
        "/admin/asr-corrections?source=llm&status=pending",
        cookies=auth_admin["cookies"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body, "candidate must be listed"
    assert all(row["source"] == "llm" and row["status"] == "pending" for row in body)
    assert any(row["wrong"] == f"候選{asr_show['suffix']}" for row in body)


async def test_approve_activates_rule_for_resolution(client, auth_admin, asr_show):
    from app.services.asr_correction import load_rules

    cid = await _seed_candidate(asr_show["show_id"], asr_show["suffix"])
    r = await client.post(
        f"/admin/asr-corrections/{cid}/approve",
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["enabled"] is True

    async with AsyncSessionFactory() as db:
        rules = await load_rules(db, asr_show["show_id"])
    assert any(rule.wrong == f"候選{asr_show['suffix']}" for rule in rules), (
        "approved candidate must enter load_rules resolution"
    )


async def test_reject_excludes_rule_from_resolution(client, auth_admin, asr_show):
    from app.services.asr_correction import load_rules

    cid = await _seed_candidate(asr_show["show_id"], asr_show["suffix"])
    r = await client.post(
        f"/admin/asr-corrections/{cid}/reject",
        cookies=auth_admin["cookies"],
        headers=auth_admin["csrf_headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "rejected" and body["enabled"] is False

    async with AsyncSessionFactory() as db:
        rules = await load_rules(db, asr_show["show_id"])
    assert not any(rule.wrong == f"候選{asr_show['suffix']}" for rule in rules), (
        "rejected candidate must NOT be in load_rules resolution"
    )
