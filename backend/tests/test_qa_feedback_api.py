"""POST /qa-feedback — append-only thumbs vote endpoint."""
import socket

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

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


@db_required
async def test_anonymous_returns_401():
    # Origin header required so CSRF middleware doesn't 403 first; the
    # endpoint's require_authenticated_user dep is what we're asserting.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"origin": "http://localhost:8080"},
    ) as ac:
        res = await ac.post(
            "/qa-feedback",
            json={"query_id": "q-1", "vote": "up", "comment": None},
        )
    assert res.status_code == 401


@db_required
async def test_logged_in_up_vote_returns_201_and_inserts_row(member_client):
    ac, user = member_client
    res = await ac.post(
        "/qa-feedback",
        json={"query_id": "q-7", "vote": "up", "comment": None},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["vote"] == "up"
    assert "id" in body
    assert "created_at" in body

    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(
                select(QAFeedback).where(
                    QAFeedback.user_id == user.id,
                    QAFeedback.query_id == "q-7",
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].vote == "up"
    assert rows[0].comment is None


@db_required
async def test_re_vote_inserts_new_row_old_row_untouched(member_client):
    ac, user = member_client
    res1 = await ac.post(
        "/qa-feedback",
        json={"query_id": "q-1", "vote": "up", "comment": None},
    )
    assert res1.status_code == 201
    first_id = res1.json()["id"]

    res2 = await ac.post(
        "/qa-feedback",
        json={"query_id": "q-1", "vote": "down", "comment": "Wrong context"},
    )
    assert res2.status_code == 201
    assert res2.json()["id"] != first_id

    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(
                select(QAFeedback).where(
                    QAFeedback.user_id == user.id,
                    QAFeedback.query_id == "q-1",
                )
            )
        ).scalars().all()
    assert len(rows) == 2
    # The original up vote row's vote field must still be 'up' (no in-place update).
    original = next(r for r in rows if str(r.id) == first_id)
    assert original.vote == "up"


@db_required
async def test_invalid_vote_returns_422(member_client):
    ac, _ = member_client
    res = await ac.post(
        "/qa-feedback",
        json={"query_id": "q-1", "vote": "maybe"},
    )
    assert res.status_code == 422
