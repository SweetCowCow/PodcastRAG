"""Tests for /admin/eval/runs endpoints + the eval_reminder beat task."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


def _write_report(results_dir: Path, slug: str, run_id: str, **overrides) -> Path:
    """Helper: write a fake eval report JSON with the canonical filename."""
    report = {
        "dataset": slug,
        "version": "v2",
        "run_id": run_id,
        "backend": "http://test",
        "judge_model": "gpt-5-nano",
        "top_k": 5,
        "n_items": 48,
        "metrics": {
            "overall": {
                "n": 48,
                "n_scored_retrieval": 42,
                "recall_at_k_mean": 0.42,
                "mrr": 0.31,
                "judge_score_mean": 0.74,
                "latency_p95_ms": 350.0,
            },
            "by_type": {},
        },
        "items": [],
    }
    report.update(overrides)
    path = results_dir / f"eval-{slug}-{run_id}.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


# ────────────────────────────────────────────────────────────────────
# Endpoint tests
# ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_eval_runs_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/eval/runs")
    assert resp.status_code == 401


@db_required
@pytest.mark.asyncio
async def test_eval_runs_member_returns_403(auth_member):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/eval/runs", cookies=auth_member["cookies"])
    assert resp.status_code == 403


@db_required
@pytest.mark.asyncio
async def test_eval_runs_admin_lists_sorted_desc(tmp_path, auth_admin):
    """Admin sees runs sorted newest-first; older runs come after newer ones."""
    from app.api.admin import eval_runs

    results = tmp_path / "results"
    results.mkdir()
    _write_report(results, "show-a", "20260101T120000Z")
    _write_report(results, "show-b", "20260601T120000Z")
    _write_report(results, "show-a", "20260301T120000Z")

    with patch.object(eval_runs, "RESULTS_DIR", results):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/admin/eval/runs", cookies=auth_admin["cookies"])

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["runs"]) == 3
    run_ids = [r["run_id"] for r in body["runs"]]
    assert run_ids == sorted(run_ids, reverse=True)
    first = body["runs"][0]
    assert first["dataset"] == "show-b"
    assert first["recall_at_k_mean"] == 0.42
    assert first["judge_model"] == "gpt-5-nano"


@db_required
@pytest.mark.asyncio
async def test_eval_run_detail_returns_full_report(tmp_path, auth_admin):
    from app.api.admin import eval_runs

    results = tmp_path / "results"
    results.mkdir()
    _write_report(results, "show-x", "20260201T080000Z", n_items=99)

    with patch.object(eval_runs, "RESULTS_DIR", results):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/eval/runs/20260201T080000Z",
                cookies=auth_admin["cookies"],
            )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert report["dataset"] == "show-x"
    assert report["n_items"] == 99


@db_required
@pytest.mark.asyncio
async def test_eval_run_detail_404_when_missing(tmp_path, auth_admin):
    from app.api.admin import eval_runs

    results = tmp_path / "results"
    results.mkdir()  # empty

    with patch.object(eval_runs, "RESULTS_DIR", results):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/admin/eval/runs/20260101T000000Z",
                cookies=auth_admin["cookies"],
            )
    assert resp.status_code == 404


# ────────────────────────────────────────────────────────────────────
# Reminder beat task tests
# ────────────────────────────────────────────────────────────────────

def _seed_dataset(datasets_dir: Path, slug: str, show_id: str = "00000000-0000-0000-0000-000000000001"):
    payload = {
        "show_slug": slug,
        "show_id": show_id,
        "version": "v1",
        "created_at": "2026-01-01",
        "items": [],
    }
    (datasets_dir / f"{slug}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.asyncio
async def test_reminder_skips_when_zsend_not_configured(monkeypatch):
    from app.workers import eval_reminder
    from app.core.config import settings

    monkeypatch.setattr(settings, "zsend_api_key", "")
    result = await eval_reminder._run()
    assert result == {"skipped": "zsend_unconfigured"}


@pytest.mark.asyncio
async def test_reminder_finds_stale_and_never_run(tmp_path, monkeypatch):
    """A show with last run >30d ago AND a show that never ran both flag stale."""
    from app.workers import eval_reminder

    datasets = tmp_path / "datasets"
    results = tmp_path / "results"
    datasets.mkdir()
    results.mkdir()
    _seed_dataset(datasets, "ancient-show")
    _seed_dataset(datasets, "never-run-show", "00000000-0000-0000-0000-000000000002")
    # Old run 60 days ago
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y%m%dT%H%M%SZ")
    _write_report(results, "ancient-show", old_ts)

    monkeypatch.setattr(eval_reminder, "DATASETS_DIR", datasets)
    monkeypatch.setattr(eval_reminder, "RESULTS_DIR", results)

    now = datetime.now(timezone.utc)
    stale = eval_reminder._stale_shows(now)
    slugs = {s["slug"] for s in stale}
    assert slugs == {"ancient-show", "never-run-show"}

    never = next(s for s in stale if s["slug"] == "never-run-show")
    assert never["last_run"] is None
    ancient = next(s for s in stale if s["slug"] == "ancient-show")
    assert ancient["days_stale"] >= 60


@pytest.mark.asyncio
async def test_reminder_skips_recent_run(tmp_path, monkeypatch):
    """A show with last run within STALE_DAYS is NOT flagged."""
    from app.workers import eval_reminder

    datasets = tmp_path / "datasets"
    results = tmp_path / "results"
    datasets.mkdir()
    results.mkdir()
    _seed_dataset(datasets, "fresh-show")
    fresh_ts = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y%m%dT%H%M%SZ")
    _write_report(results, "fresh-show", fresh_ts)

    monkeypatch.setattr(eval_reminder, "DATASETS_DIR", datasets)
    monkeypatch.setattr(eval_reminder, "RESULTS_DIR", results)

    stale = eval_reminder._stale_shows(datetime.now(timezone.utc))
    assert stale == []


def test_reminder_email_compose_lists_each_show():
    from app.workers import eval_reminder

    stale = [
        {"slug": "show-a", "show_id": "x", "last_run": None, "days_stale": None},
        {
            "slug": "show-b",
            "show_id": "y",
            "last_run": "2026-01-01T00:00:00+00:00",
            "days_stale": 99,
        },
    ]
    subject, body = eval_reminder._compose_email(stale)
    assert "2 show(s)" in subject
    assert "show-a" in body
    assert "never run" in body
    assert "show-b" in body
    assert "99 days ago" in body
