"""Tests for app.workers.appeal_digest.send_appeal_digest.

Uses an in-memory sqlite engine for the worker by monkeypatching
``create_async_engine`` inside the worker module — keeps tests independent
of the dev postgres reachability (pre-existing baseline failure mode in
this repo).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.account_appeal import AccountAppeal
from app.workers import appeal_digest


@pytest_asyncio.fixture
async def sqlite_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: AccountAppeal.__table__.create(c, checkfirst=True)
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def worker_session(sqlite_engine, monkeypatch):
    """Monkeypatch the worker's create_async_engine so _run() uses our
    in-memory sqlite engine. Returns a session maker for test setup."""
    # Make the worker's `finally: await engine.dispose()` a no-op so our
    # shared sqlite engine survives until post-assertion check. Wrap the
    # engine in a tiny proxy that overrides dispose() only.
    class _EngineProxy:
        def __init__(self, e):
            self._e = e

        async def dispose(self):
            return None

        def __getattr__(self, name):
            return getattr(self._e, name)

    proxy = _EngineProxy(sqlite_engine)

    def _fake_create_engine(_url, **_kwargs):
        return proxy

    monkeypatch.setattr(appeal_digest, "create_async_engine", _fake_create_engine)
    return async_sessionmaker(sqlite_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _zsend_configured(monkeypatch):
    monkeypatch.setattr(
        appeal_digest.settings, "zsend_api_key", "test-key", raising=False
    )
    monkeypatch.setattr(
        appeal_digest.settings,
        "zsend_from_email",
        "noreply@test.local",
        raising=False,
    )
    monkeypatch.setattr(
        appeal_digest.settings,
        "zsend_admin_to_email",
        "admin1@test.local,admin2@test.local",
        raising=False,
    )


@pytest.mark.asyncio
async def test_digest_sends_and_marks_notified(worker_session):
    """Two new appeals → both recipients emailed, both rows stamped."""
    async with worker_session() as db:
        for i in range(2):
            db.add(
                AccountAppeal(
                    email=f"appeal-{i}@example.com",
                    reason=f"digest test reason {i}",
                )
            )
        await db.commit()

    sent = []

    async def fake_send(to, subject, body):
        sent.append((to, subject, body))

    with patch.object(
        appeal_digest, "send_email", new=AsyncMock(side_effect=fake_send)
    ):
        result = await appeal_digest._run()

    assert result == {"sent_count": 2, "recipient_count": 2}
    assert len(sent) == 2
    to_addrs = sorted(s[0] for s in sent)
    assert to_addrs == ["admin1@test.local", "admin2@test.local"]
    for _to, subject, body in sent:
        assert "2 筆" in subject
        assert "appeal-0@example.com" in body
        assert "appeal-1@example.com" in body

    from sqlalchemy import select
    async with worker_session() as db:
        rows = list((await db.execute(select(AccountAppeal))).scalars().all())
        assert len(rows) == 2
        for r in rows:
            assert r.notified_at is not None


@pytest.mark.asyncio
async def test_digest_empty_skips_email(worker_session):
    """No new rows → no email sent, return {sent_count: 0}."""
    sent = []

    async def fake_send(to, subject, body):
        sent.append(to)

    with patch.object(
        appeal_digest, "send_email", new=AsyncMock(side_effect=fake_send)
    ):
        result = await appeal_digest._run()

    assert result == {"sent_count": 0, "recipient_count": 0}
    assert sent == []


@pytest.mark.asyncio
async def test_digest_skips_already_notified(worker_session):
    """Rows with notified_at set are NOT re-sent."""
    async with worker_session() as db:
        db.add(
            AccountAppeal(
                email="already@example.com",
                reason="already notified",
                notified_at=datetime.now(timezone.utc) - timedelta(hours=10),
            )
        )
        await db.commit()

    sent = []

    async def fake_send(to, subject, body):
        sent.append(to)

    with patch.object(
        appeal_digest, "send_email", new=AsyncMock(side_effect=fake_send)
    ):
        result = await appeal_digest._run()

    assert result["sent_count"] == 0
    assert sent == []
