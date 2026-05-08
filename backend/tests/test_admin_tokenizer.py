"""Tests for /admin/tokenizer/* CRUD + reload."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.main import app
from app.models.tokenizer_term import TokenizerCustomTerm
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest_asyncio.fixture
async def clean_terms(db_session):
    await db_session.execute(
        delete(TokenizerCustomTerm).where(
            TokenizerCustomTerm.term.like("pytest-%")
        )
    )
    await db_session.commit()
    yield
    await db_session.execute(
        delete(TokenizerCustomTerm).where(
            TokenizerCustomTerm.term.like("pytest-%")
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_unauthenticated_401():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/admin/tokenizer/terms")
        assert r.status_code == 401


@db_required
@pytest.mark.asyncio
async def test_list_member_403(auth_member):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/admin/tokenizer/terms", cookies=auth_member["cookies"]
        )
        assert r.status_code == 403


@db_required
@pytest.mark.asyncio
async def test_admin_create_list_delete(auth_admin, clean_terms):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/admin/tokenizer/terms",
            json={"term": "pytest-顏色"},
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
        assert r.status_code == 201
        body = r.json()
        assert body["term"] == "pytest-顏色"
        assert body["weight"] == 100
        assert body["source"] == "manual"
        new_id = body["id"]

        r = await c.get(
            "/admin/tokenizer/terms", cookies=auth_admin["cookies"]
        )
        assert r.status_code == 200
        assert any(item["term"] == "pytest-顏色" for item in r.json())

        r = await c.delete(
            f"/admin/tokenizer/terms/{new_id}",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
        assert r.status_code == 204


@db_required
@pytest.mark.asyncio
async def test_duplicate_term_returns_409(auth_admin, clean_terms):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.post(
            "/admin/tokenizer/terms",
            json={"term": "pytest-台通"},
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
        r = await c.post(
            "/admin/tokenizer/terms",
            json={"term": "pytest-台通"},
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
        assert r.status_code == 409
        assert r.json()["detail"]["error_code"] == "duplicate_term"


@db_required
@pytest.mark.asyncio
async def test_reload_returns_202(auth_admin):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/admin/tokenizer/reload",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
        assert r.status_code == 202
