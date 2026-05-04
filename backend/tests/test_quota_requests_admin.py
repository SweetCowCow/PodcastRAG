"""Admin quota_requests endpoints."""
import socket
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.quota_request import QuotaRequest, QuotaRequestStatus
from app.models.user import User


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


def _admin_client(auth_admin):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"origin": "http://localhost:8080", **auth_admin["csrf_headers"]}
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
        cookies=auth_admin["cookies"],
    )


def _member_client(auth_member):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"origin": "http://localhost:8080", **auth_member["csrf_headers"]}
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
        cookies=auth_member["cookies"],
    )


@db_required
async def test_approve_adds_quota_and_marks_processed(auth_admin, auth_member):
    member = auth_member["user"]
    initial_quota = member.quota_remaining

    async with AsyncSessionFactory() as db:
        qr = QuotaRequest(
            user_id=member.id,
            reason="approve test reason 10+",
            status=QuotaRequestStatus.pending.value,
        )
        db.add(qr)
        await db.commit()
        await db.refresh(qr)
        request_id = qr.id

    async with _admin_client(auth_admin) as ac:
        res = await ac.post(
            f"/admin/quota-requests/{request_id}/approve",
            json={"amount": 50},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "approved"
    assert body["quota_remaining"] == initial_quota + 50

    async with AsyncSessionFactory() as db:
        row = await db.get(QuotaRequest, request_id)
        assert row.status == "approved"
        assert row.granted_amount == 50
        assert row.processed_at is not None
        assert row.processed_by == auth_admin["user"].id

        u = await db.get(User, member.id)
        assert u.quota_remaining == initial_quota + 50


@db_required
async def test_reject_does_not_modify_quota(auth_admin, auth_member):
    member = auth_member["user"]
    initial_quota = member.quota_remaining

    async with AsyncSessionFactory() as db:
        qr = QuotaRequest(
            user_id=member.id,
            reason="reject test reason 10+",
            status=QuotaRequestStatus.pending.value,
        )
        db.add(qr)
        await db.commit()
        await db.refresh(qr)
        request_id = qr.id

    async with _admin_client(auth_admin) as ac:
        res = await ac.post(
            f"/admin/quota-requests/{request_id}/reject",
            json={"note": "理由不充分"},
        )
    assert res.status_code == 200

    async with AsyncSessionFactory() as db:
        row = await db.get(QuotaRequest, request_id)
        assert row.status == "rejected"
        assert row.rejection_note == "理由不充分"
        assert row.processed_by == auth_admin["user"].id

        u = await db.get(User, member.id)
        assert u.quota_remaining == initial_quota


@db_required
async def test_already_processed_returns_409(auth_admin, auth_member):
    member = auth_member["user"]

    async with AsyncSessionFactory() as db:
        qr = QuotaRequest(
            user_id=member.id,
            reason="already processed test reason 10+",
            status=QuotaRequestStatus.approved.value,
            processed_at=datetime.now(timezone.utc),
            granted_amount=20,
        )
        db.add(qr)
        await db.commit()
        await db.refresh(qr)
        request_id = qr.id

    async with _admin_client(auth_admin) as ac:
        res = await ac.post(
            f"/admin/quota-requests/{request_id}/approve",
            json={"amount": 30},
        )
    assert res.status_code == 409
    assert res.json()["detail"]["error_code"] == "already_processed"


@db_required
async def test_approve_clamps_to_quota_ceiling(auth_admin, auth_member):
    member = auth_member["user"]

    # Push user's quota near the ceiling
    async with AsyncSessionFactory() as db:
        u = await db.get(User, member.id)
        u.quota_remaining = 999_950
        await db.commit()

        qr = QuotaRequest(
            user_id=member.id,
            reason="clamp test reason 10+",
            status=QuotaRequestStatus.pending.value,
        )
        db.add(qr)
        await db.commit()
        await db.refresh(qr)
        request_id = qr.id

    async with _admin_client(auth_admin) as ac:
        res = await ac.post(
            f"/admin/quota-requests/{request_id}/approve",
            json={"amount": 1000},
        )
    assert res.status_code == 200
    assert res.json()["quota_remaining"] == 1_000_000


@db_required
async def test_member_cannot_call_admin_endpoints(auth_member):
    bogus_id = uuid.uuid4()
    async with _member_client(auth_member) as ac:
        res = await ac.get("/admin/quota-requests")
    assert res.status_code == 403


@db_required
async def test_unauthenticated_cannot_call_admin_endpoints():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:8080"},
    ) as ac:
        res = await ac.get("/admin/quota-requests")
    assert res.status_code == 401


@db_required
async def test_list_filters_by_status(auth_admin, auth_member):
    member = auth_member["user"]
    async with AsyncSessionFactory() as db:
        for status_val in (
            QuotaRequestStatus.pending.value,
            QuotaRequestStatus.approved.value,
            QuotaRequestStatus.rejected.value,
        ):
            db.add(
                QuotaRequest(
                    user_id=member.id,
                    reason=f"{status_val} reason 10+chars",
                    status=status_val,
                    processed_at=(
                        datetime.now(timezone.utc) if status_val != "pending" else None
                    ),
                    granted_amount=10 if status_val == "approved" else None,
                    rejection_note="bad" if status_val == "rejected" else None,
                )
            )
        await db.commit()

    async with _admin_client(auth_admin) as ac:
        res = await ac.get("/admin/quota-requests?status=approved")
    assert res.status_code == 200
    rows = res.json()
    # Filter respected: each row has status approved
    for r in rows:
        assert r["status"] == "approved"
        assert r["user_email"] == member.email
        assert "user_quota_remaining" in r
