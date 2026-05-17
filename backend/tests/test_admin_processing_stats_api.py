"""Tests for `/admin/processing-stats` admin endpoint.

Covers the four scenarios in `processing-progress-overview` spec:

- Response shape (three dimensions + last_24h + as_of)
- topic_seg dual count (segment ratio AND episode_ratio)
- last_24h failures grouped by task_name
- Non-admin gets 403, unauthenticated gets 401
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import admin_processing_stats as stats_module
from app.main import app
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest.mark.asyncio
async def test_unauthenticated_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/processing-stats")
        assert resp.status_code == 401
        assert resp.json()["detail"]["error_code"] == "not_authenticated"


@db_required
@pytest.mark.asyncio
async def test_member_returns_403(auth_member, monkeypatch):
    monkeypatch.setattr(stats_module, "_fetch_failures", lambda now: [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/processing-stats", cookies=auth_member["cookies"]
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error_code"] == "forbidden"


@db_required
@pytest.mark.asyncio
async def test_admin_response_shape(auth_admin, monkeypatch):
    monkeypatch.setattr(stats_module, "_fetch_failures", lambda now: [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/processing-stats", cookies=auth_admin["cookies"]
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "transcription",
            "summary",
            "topic_seg",
            "last_24h",
            "as_of",
        }
        # transcription / summary shape
        for key in ("transcription", "summary"):
            sub = body[key]
            assert set(sub.keys()) == {"completed_episodes", "total_episodes", "ratio"}
            assert isinstance(sub["completed_episodes"], int)
            assert isinstance(sub["total_episodes"], int)
            assert isinstance(sub["ratio"], (int, float))
        # topic_seg dual-count shape
        ts = body["topic_seg"]
        assert set(ts.keys()) == {
            "completed_segments",
            "total_segments",
            "ratio",
            "completed_episodes",
            "total_episodes_with_transcript",
            "episode_ratio",
        }
        # last_24h shape
        l24 = body["last_24h"]
        assert set(l24.keys()) == {
            "transcribed_episodes",
            "labeled_segments",
            "failures",
        }
        assert isinstance(l24["failures"], list)
        # as_of is parseable ISO 8601 UTC
        datetime.fromisoformat(body["as_of"].replace("Z", "+00:00"))


@db_required
@pytest.mark.asyncio
async def test_topic_seg_includes_segment_and_episode_counts(auth_admin, monkeypatch):
    """topic_seg.ratio is segment-based; episode_ratio is episode-based."""
    monkeypatch.setattr(stats_module, "_fetch_failures", lambda now: [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/processing-stats", cookies=auth_admin["cookies"]
        )
        assert resp.status_code == 200
        ts = resp.json()["topic_seg"]
        # Both fields present and non-negative (don't assume non-empty DB).
        assert ts["completed_segments"] >= 0
        assert ts["total_segments"] >= 0
        assert ts["completed_episodes"] >= 0
        assert ts["total_episodes_with_transcript"] >= 0
        # Ratios in [0, 1]
        assert 0.0 <= ts["ratio"] <= 1.0
        assert 0.0 <= ts["episode_ratio"] <= 1.0


@db_required
@pytest.mark.asyncio
async def test_last_24h_failures_grouped_by_task_name(auth_admin, monkeypatch):
    """Failures from `_fetch_failures()` flow through grouped by task_name."""

    def fake_fetch(now):
        return [
            {
                "task_name": "app.workers.tasks.transcribe_episode",
                "count": 10,
                "sample_error": "413 Maximum content size limit exceeded",
            },
            {
                "task_name": "app.workers.topic_task.classify_episode_topics",
                "count": 4,
                "sample_error": "ConnectionError",
            },
        ]

    monkeypatch.setattr(stats_module, "_fetch_failures", fake_fetch)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/admin/processing-stats", cookies=auth_admin["cookies"]
        )
        assert resp.status_code == 200
        failures = resp.json()["last_24h"]["failures"]
        assert len(failures) == 2
        task_names = {f["task_name"] for f in failures}
        assert task_names == {
            "app.workers.tasks.transcribe_episode",
            "app.workers.topic_task.classify_episode_topics",
        }
        for entry in failures:
            assert isinstance(entry["count"], int)
            assert entry["count"] > 0
            assert isinstance(entry["sample_error"], str)


# ── unit tests for _fetch_failures: in-process fake Redis client ──


class _FakeRedis:
    """Minimal stand-in for redis-py exposing scan_iter + get."""

    def __init__(self, payloads: dict[str, str]):
        self._payloads = payloads

    def scan_iter(self, match: str, count: int = 500):
        # naive prefix match supporting trailing '*'
        prefix = match.rstrip("*")
        for k in self._payloads:
            if k.startswith(prefix):
                yield k

    def get(self, key: str):
        return self._payloads.get(key)


def _meta(task: str, status: str, date_done: datetime, exc_message: str = "boom"):
    return json.dumps(
        {
            "task": task,
            "status": status,
            "date_done": date_done.isoformat(),
            "result": {"exc_message": exc_message, "exc_type": "RuntimeError"},
        }
    )


def test_fetch_failures_groups_by_task_and_filters_24h(monkeypatch):
    now = datetime.now(timezone.utc)
    inside = now - timedelta(hours=1)
    outside = now - timedelta(hours=30)
    payloads = {
        "celery-task-meta-1": _meta(
            "app.workers.tasks.transcribe_episode", "FAILURE", inside, "413 too big"
        ),
        "celery-task-meta-2": _meta(
            "app.workers.tasks.transcribe_episode", "FAILURE", inside, "another"
        ),
        # outside 24h window — must be dropped
        "celery-task-meta-3": _meta(
            "app.workers.tasks.transcribe_episode", "FAILURE", outside, "old"
        ),
        # SUCCESS — must be dropped
        "celery-task-meta-4": _meta(
            "app.workers.tasks.transcribe_episode", "SUCCESS", inside, ""
        ),
        # different task family
        "celery-task-meta-5": _meta(
            "app.workers.topic_task.classify_episode_topics",
            "FAILURE",
            inside,
            "connection refused",
        ),
        # not a reported task family — dropped
        "celery-task-meta-6": _meta(
            "app.workers.db_backup.run_db_backup", "FAILURE", inside, "ignored"
        ),
    }

    class _FakeBackend:
        client = _FakeRedis(payloads)

    class _FakeApp:
        backend = _FakeBackend()

    monkeypatch.setattr(stats_module, "celery_app", _FakeApp(), raising=False)
    # The function imports `celery_app` lazily inside the function body, so
    # also patch the import target:
    import app.workers.celery_app as celery_app_mod

    monkeypatch.setattr(celery_app_mod, "celery_app", _FakeApp())

    result = stats_module._fetch_failures(now)
    by_name = {e["task_name"]: e for e in result}
    assert "app.workers.tasks.transcribe_episode" in by_name
    assert by_name["app.workers.tasks.transcribe_episode"]["count"] == 2
    assert "app.workers.topic_task.classify_episode_topics" in by_name
    assert by_name["app.workers.topic_task.classify_episode_topics"]["count"] == 1
    assert "app.workers.db_backup.run_db_backup" not in by_name
    # Sorted highest-count first
    assert result[0]["count"] >= result[-1]["count"]


def test_fetch_failures_returns_empty_when_backend_has_no_client(monkeypatch):
    class _FakeBackend:
        pass  # no `client` attribute

    class _FakeApp:
        backend = _FakeBackend()

    import app.workers.celery_app as celery_app_mod

    monkeypatch.setattr(celery_app_mod, "celery_app", _FakeApp())

    assert stats_module._fetch_failures(datetime.now(timezone.utc)) == []
