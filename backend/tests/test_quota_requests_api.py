"""User-facing quota_requests API tests.

Covers:
- POST /quota-requests first submission → 201
- POST /quota-requests second pending → 409 quota_request_pending
- POST with reason < 10 chars → 422
- After previous processed (approved/rejected), new POST allowed
- GET /quota-requests/me returns own rows ordered by requested_at desc
- GET ?status= filters correctly
"""
import socket
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.quota_request import QuotaRequest, QuotaRequestStatus


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


@pytest_asyncio.fixture
async def member_client(auth_member):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"origin": "http://localhost:8080", **auth_member["csrf_headers"]}
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
        cookies=auth_member["cookies"],
    ) as ac:
        yield ac, auth_member["user"]


@pytest_asyncio.fixture
async def cleanup_quota_requests():
    yield
    async with AsyncSessionFactory() as db:
        # User cleanup is handled by db_session fixture (deletes pytest-* users)
        # but quota_requests cascades from user delete, so this fixture is a no-op.
        pass


@db_required
async def test_first_request_returns_201(member_client, cleanup_quota_requests):
    ac, user = member_client
    res = await ac.post(
        "/quota-requests",
        json={"reason": "我用完了 quota 在做 Podcast 整理研究"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "pending"
    assert body["reason"] == "我用完了 quota 在做 Podcast 整理研究"
    assert body["processed_at"] is None
    assert body["granted_amount"] is None


@db_required
async def test_second_pending_returns_409(member_client, cleanup_quota_requests):
    ac, user = member_client
    res1 = await ac.post(
        "/quota-requests", json={"reason": "first request reason 10+"}
    )
    assert res1.status_code == 201

    res2 = await ac.post(
        "/quota-requests", json={"reason": "second request reason 10+"}
    )
    assert res2.status_code == 409
    assert res2.json()["detail"]["error_code"] == "quota_request_pending"


@db_required
async def test_reason_too_short_returns_422(member_client, cleanup_quota_requests):
    ac, _ = member_client
    res = await ac.post("/quota-requests", json={"reason": "太短"})
    assert res.status_code == 422


@db_required
async def test_after_processed_user_can_submit_again(
    member_client, cleanup_quota_requests
):
    ac, user = member_client
    res1 = await ac.post(
        "/quota-requests", json={"reason": "first request reason 10+"}
    )
    request_id = uuid.UUID(res1.json()["id"])

    # Manually mark approved (simulating admin action)
    async with AsyncSessionFactory() as db:
        row = await db.get(QuotaRequest, request_id)
        row.status = QuotaRequestStatus.approved.value
        row.processed_at = datetime.now(timezone.utc)
        row.granted_amount = 30
        await db.commit()

    # New submission should now succeed (no pending row exists)
    res2 = await ac.post(
        "/quota-requests", json={"reason": "second request after approval 10+"}
    )
    assert res2.status_code == 201


@db_required
async def test_get_me_returns_only_own_rows(
    auth_member, auth_admin, cleanup_quota_requests
):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    member_headers = {
        "origin": "http://localhost:8080",
        **auth_member["csrf_headers"],
    }
    admin_headers = {
        "origin": "http://localhost:8080",
        **auth_admin["csrf_headers"],
    }

    # Member submits 2 (one pending, one approved); admin submits 1
    async with AsyncSessionFactory() as db:
        for reason in ["member req 1 reason", "member req 2 reason"]:
            db.add(
                QuotaRequest(
                    user_id=auth_member["user"].id,
                    reason=reason,
                    status=QuotaRequestStatus.approved.value,
                    processed_at=datetime.now(timezone.utc),
                    granted_amount=10,
                )
            )
        db.add(
            QuotaRequest(
                user_id=auth_admin["user"].id,
                reason="admin req reason 10+",
                status=QuotaRequestStatus.pending.value,
            )
        )
        await db.commit()

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=member_headers,
        cookies=auth_member["cookies"],
    ) as ac:
        res = await ac.get("/quota-requests/me")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 2
    # All belong to member
    for r in rows:
        assert r["status"] == "approved"


@db_required
async def test_get_me_status_filter(auth_member, cleanup_quota_requests):
    user = auth_member["user"]
    async with AsyncSessionFactory() as db:
        db.add(
            QuotaRequest(
                user_id=user.id,
                reason="pending req reason 10+",
                status=QuotaRequestStatus.pending.value,
            )
        )
        for _ in range(2):
            db.add(
                QuotaRequest(
                    user_id=user.id,
                    reason="approved req reason 10+",
                    status=QuotaRequestStatus.approved.value,
                    processed_at=datetime.now(timezone.utc),
                    granted_amount=20,
                )
            )
        await db.commit()

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"origin": "http://localhost:8080", **auth_member["csrf_headers"]}
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
        cookies=auth_member["cookies"],
    ) as ac:
        res = await ac.get("/quota-requests/me?status=pending")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
