"""Tests for app.workers.quota_digest.send_quota_digest."""
import socket
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.models.quota_request import QuotaRequest, QuotaRequestStatus
from app.models.user import User
from app.services.zsend import ZSendError
from app.workers import quota_digest


def _postgres_reachable() -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", 5432))
        return True
    except OSError:
        return False
    finally:
        s.close()


db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="postgres not reachable"
)


@pytest_asyncio.fixture(autouse=True)
async def _zsend_configured(monkeypatch):
    monkeypatch.setattr(
        quota_digest.settings, "zsend_api_key", "test-key", raising=False
    )
    monkeypatch.setattr(
        quota_digest.settings,
        "zsend_from_email",
        "noreply@test.local",
        raising=False,
    )
    monkeypatch.setattr(
        quota_digest.settings,
        "zsend_admin_to_email",
        "admin1@test.local,admin2@test.local",
        raising=False,
    )


@pytest_asyncio.fixture
async def member_with_pending(auth_member):
    """Yield (user, request_ids[]) for tests that need pending rows.
    Cleaned by db_session conftest fixture (cascades on user delete)."""
    user = auth_member["user"]
    async with AsyncSessionFactory() as db:
        ids = []
        for _ in range(3):
            qr = QuotaRequest(
                user_id=user.id,
                reason="digest test reason 10+",
                status=QuotaRequestStatus.pending.value,
            )
            db.add(qr)
        await db.commit()
        rows = (
            await db.execute(
                select(QuotaRequest).where(QuotaRequest.user_id == user.id)
            )
        ).scalars().all()
        ids = [r.id for r in rows]
    yield user, ids


@db_required
@pytest.mark.asyncio
async def test_three_pending_two_recipients_sends_two_emails(member_with_pending):
    user, ids = member_with_pending
    sent = []

    async def fake_send(to, subject, body):
        sent.append((to, subject, body))

    with patch.object(quota_digest, "send_email", new=AsyncMock(side_effect=fake_send)):
        result = await quota_digest._run()

    assert result == {"sent_count": 3, "recipient_count": 2}
    assert len(sent) == 2
    to_addrs = sorted(s[0] for s in sent)
    assert to_addrs == ["admin1@test.local", "admin2@test.local"]
    # Subject mentions count
    for to, subject, body in sent:
        assert "3 筆" in subject or "3 " in subject
        assert "後台處理" in body

    # All 3 rows updated last_digest_at
    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(select(QuotaRequest).where(QuotaRequest.id.in_(ids)))
        ).scalars().all()
        for r in rows:
            assert r.last_digest_at is not None


@db_required
@pytest.mark.asyncio
async def test_already_digested_within_cooldown_skipped(auth_member):
    """Row with last_digest_at within last 6 hours is excluded from the next run."""
    user = auth_member["user"]
    fresh_id = uuid.uuid4()
    stale_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with AsyncSessionFactory() as db:
        db.add(
            QuotaRequest(
                id=fresh_id,
                user_id=user.id,
                reason="recently digested 10+",
                status=QuotaRequestStatus.pending.value,
                last_digest_at=now - timedelta(minutes=30),
            )
        )
        db.add(
            QuotaRequest(
                id=stale_id,
                user_id=user.id,
                reason="never digested 10+chars",
                status=QuotaRequestStatus.pending.value,
                last_digest_at=None,
            )
        )
        await db.commit()

    sent_bodies = []

    async def fake_send(to, subject, body):
        sent_bodies.append(body)

    with patch.object(quota_digest, "send_email", new=AsyncMock(side_effect=fake_send)):
        result = await quota_digest._run()

    assert result["sent_count"] == 1
    # Body lists exactly 1 item
    for body in sent_bodies:
        assert "1 筆" in body or "1." in body
        assert "never digested" in body
        assert "recently digested" not in body

    # Only the stale row got updated
    async with AsyncSessionFactory() as db:
        fresh = await db.get(QuotaRequest, fresh_id)
        stale = await db.get(QuotaRequest, stale_id)
        # Fresh row's last_digest_at should be untouched (still ~30 min ago)
        assert fresh.last_digest_at < now - timedelta(minutes=10)
        # Stale row got bumped
        assert stale.last_digest_at > now - timedelta(minutes=1)


@db_required
@pytest.mark.asyncio
async def test_no_pending_does_not_call_zsend():
    sent = []

    async def fake_send(to, subject, body):
        sent.append(to)

    with patch.object(quota_digest, "send_email", new=AsyncMock(side_effect=fake_send)):
        result = await quota_digest._run()

    assert result["sent_count"] == 0
    assert sent == []


@db_required
@pytest.mark.asyncio
async def test_zsend_unconfigured_skips_gracefully(monkeypatch):
    monkeypatch.setattr(
        quota_digest.settings, "zsend_api_key", None, raising=False
    )
    sent = []

    async def fake_send(to, subject, body):
        sent.append(to)

    with patch.object(quota_digest, "send_email", new=AsyncMock(side_effect=fake_send)):
        result = await quota_digest._run()

    assert result == {"skipped": "zsend_unconfigured"}
    assert sent == []


@db_required
@pytest.mark.asyncio
async def test_retryable_zsend_error_propagates(member_with_pending):
    """A retryable ZSendError on the first send bubbles up so Celery autoretry kicks in."""
    fail_send = AsyncMock(side_effect=ZSendError("503", retryable=True))
    with patch.object(quota_digest, "send_email", new=fail_send):
        with pytest.raises(ZSendError) as exc_info:
            await quota_digest._run()
    assert exc_info.value.retryable is True


@db_required
@pytest.mark.asyncio
async def test_non_retryable_zsend_error_continues_to_next_recipient(
    member_with_pending,
):
    """A 4xx ZSendError on one recipient is logged but the loop continues for the rest."""
    calls = []

    async def fake_send(to, subject, body):
        calls.append(to)
        if to == "admin1@test.local":
            raise ZSendError("422 bad addr", retryable=False)

    with patch.object(quota_digest, "send_email", new=AsyncMock(side_effect=fake_send)):
        result = await quota_digest._run()

    # Both recipients attempted
    assert calls == ["admin1@test.local", "admin2@test.local"]
    # Result counts both as recipients (even though one failed)
    assert result["recipient_count"] == 2
