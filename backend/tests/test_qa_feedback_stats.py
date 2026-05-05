"""GET /qa-feedback/stats — admin-only 7-day rolling thumbs ratio."""
import socket
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.qa_feedback import QAFeedback


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
async def admin_client(auth_admin):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"origin": "http://localhost:8080", **auth_admin["csrf_headers"]}
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
        cookies=auth_admin["cookies"],
    ) as ac:
        yield ac, auth_admin["user"]


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


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_qa_feedback():
    yield
    async with AsyncSessionFactory() as db:
        await db.execute(delete(QAFeedback))
        await db.commit()


async def _seed(db, *, user_id, query_id, vote, created_at):
    db.add(
        QAFeedback(
            user_id=user_id,
            query_id=query_id,
            vote=vote,
            created_at=created_at,
        )
    )


@db_required
async def test_admin_gets_stats_with_mixed_votes(admin_client):
    ac, admin = admin_client
    now = datetime.now(timezone.utc)
    async with AsyncSessionFactory() as db:
        # 8 distinct (user, query) pairs with up, 2 with down — re-using admin id
        # is fine since (user_id, query_id) is the dedup key.
        for i in range(8):
            await _seed(
                db, user_id=admin.id, query_id=f"q-up-{i}", vote="up",
                created_at=now - timedelta(hours=1),
            )
        for i in range(2):
            await _seed(
                db, user_id=admin.id, query_id=f"q-down-{i}", vote="down",
                created_at=now - timedelta(hours=1),
            )
        await db.commit()

    res = await ac.get("/qa-feedback/stats")
    assert res.status_code == 200
    body = res.json()
    assert body == {"up_7d": 8, "down_7d": 2, "total_7d": 10, "ratio": 0.80}


@db_required
async def test_empty_stats_returns_null_ratio(admin_client):
    ac, _ = admin_client
    res = await ac.get("/qa-feedback/stats")
    assert res.status_code == 200
    assert res.json() == {"up_7d": 0, "down_7d": 0, "total_7d": 0, "ratio": None}


@db_required
async def test_re_vote_counted_only_as_latest(admin_client):
    ac, admin = admin_client
    now = datetime.now(timezone.utc)
    async with AsyncSessionFactory() as db:
        # Same (user, query): up at T-2h, then down at T-1h. Latest = down.
        await _seed(
            db, user_id=admin.id, query_id="q-flip", vote="up",
            created_at=now - timedelta(hours=2),
        )
        await _seed(
            db, user_id=admin.id, query_id="q-flip", vote="down",
            created_at=now - timedelta(hours=1),
        )
        await db.commit()

    res = await ac.get("/qa-feedback/stats")
    assert res.status_code == 200
    body = res.json()
    assert body["up_7d"] == 0
    assert body["down_7d"] == 1
    assert body["total_7d"] == 1


@db_required
async def test_rolling_7_day_excludes_8_day_old(admin_client):
    ac, admin = admin_client
    now = datetime.now(timezone.utc)
    async with AsyncSessionFactory() as db:
        # In window
        await _seed(
            db, user_id=admin.id, query_id="q-recent", vote="up",
            created_at=now - timedelta(days=3),
        )
        # Outside window (8 days old)
        await _seed(
            db, user_id=admin.id, query_id="q-old", vote="up",
            created_at=now - timedelta(days=8),
        )
        await db.commit()

    res = await ac.get("/qa-feedback/stats")
    assert res.status_code == 200
    assert res.json()["up_7d"] == 1
    assert res.json()["total_7d"] == 1


@db_required
async def test_non_admin_returns_403(member_client):
    ac, _ = member_client
    res = await ac.get("/qa-feedback/stats")
    assert res.status_code == 403


@db_required
async def test_anonymous_returns_401():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get("/qa-feedback/stats")
    assert res.status_code == 401
