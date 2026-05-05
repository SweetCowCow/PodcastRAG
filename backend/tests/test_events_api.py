"""POST /events — public client event ingestion (citation_click v1)."""
import socket

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionFactory
from app.main import app
from app.models.event import Event


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
async def _cleanup_events_and_redis():
    """Wipe events rows and the rate-limit Redis key prefix between tests."""
    yield
    async with AsyncSessionFactory() as db:
        await db.execute(delete(Event))
        await db.commit()
    try:
        from app.core.rate_limit import _get_redis  # type: ignore
        r = _get_redis()
        for key in r.scan_iter("rl:min:ip:events:*"):
            r.delete(key)
    except Exception:
        pass


def _payload():
    return {
        "event_type": "citation_click",
        "payload": {"query_id": "q-1", "chunk_id": "c-9", "position": 2},
    }


@db_required
async def test_anonymous_insert_returns_202_and_user_id_null():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/events", json=_payload())
    assert res.status_code == 202

    async with AsyncSessionFactory() as db:
        rows = (await db.execute(select(Event))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == "citation_click"
    assert row.user_id is None
    assert row.event_payload == {
        "query_id": "q-1", "chunk_id": "c-9", "position": 2,
    }


@db_required
async def test_logged_in_event_tagged_with_user_id(auth_member):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"origin": "http://localhost:8080", **auth_member["csrf_headers"]}
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=headers,
        cookies=auth_member["cookies"],
    ) as ac:
        res = await ac.post("/events", json=_payload())
    assert res.status_code == 202

    async with AsyncSessionFactory() as db:
        rows = (await db.execute(select(Event))).scalars().all()
    assert len(rows) == 1
    assert rows[0].user_id == auth_member["user"].id


@db_required
async def test_unknown_event_type_returns_422_no_row():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/events",
            json={"event_type": "scroll_depth", "payload": {}},
        )
    assert res.status_code == 422

    async with AsyncSessionFactory() as db:
        rows = (await db.execute(select(Event))).scalars().all()
    assert len(rows) == 0


@db_required
async def test_payload_missing_chunk_id_returns_422():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post(
            "/events",
            json={
                "event_type": "citation_click",
                "payload": {"query_id": "q-1"},
            },
        )
    assert res.status_code == 422


@db_required
async def test_per_ip_rate_limit_returns_429_after_60(monkeypatch):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    # Use a unique forwarded IP so this test isn't polluted by neighbors.
    headers = {"x-forwarded-for": "203.0.113.42"}
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as ac:
        for i in range(60):
            res = await ac.post("/events", json=_payload())
            assert res.status_code == 202, f"req {i} got {res.status_code}"
        res = await ac.post("/events", json=_payload())
    assert res.status_code == 429
