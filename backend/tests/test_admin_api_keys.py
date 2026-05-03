"""Tests for /admin/api-keys CRUD."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.main import app
from app.models.ai_step import AiStep
from app.models.api_key import ApiKey
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest_asyncio.fixture
async def clean_keys(db_session):
    """Snapshot+restore ai_steps.api_key_id; delete pytest-* keys before+after.

    Avoids clobbering migration-seeded api_key_id pointers so tests in other
    files that rely on RAG / embedding endpoints still work after this fixture
    has run.
    """
    snapshot = {
        r.step_key: r.api_key_id
        for r in (await db_session.execute(select(AiStep))).scalars().all()
    }

    async def _wipe_pytest_keys():
        # First, null out any ai_steps row that points to a pytest-* key so the
        # FK delete is safe.
        await db_session.execute(
            update(AiStep)
            .where(
                AiStep.api_key_id.in_(
                    select(ApiKey.id).where(ApiKey.label.like("pytest-%"))
                )
            )
            .values(api_key_id=None)
        )
        await db_session.execute(
            delete(ApiKey).where(ApiKey.label.like("pytest-%"))
        )
        await db_session.commit()

    await _wipe_pytest_keys()
    yield
    await _wipe_pytest_keys()
    # Restore migration-seeded api_key_id values.
    for step_key, api_key_id in snapshot.items():
        await db_session.execute(
            update(AiStep).where(AiStep.step_key == step_key).values(api_key_id=api_key_id)
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_unauthenticated_401():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/admin/api-keys")
        assert r.status_code == 401


@db_required
@pytest.mark.asyncio
async def test_list_member_403(auth_member):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/admin/api-keys", cookies=auth_member["cookies"])
        assert r.status_code == 403


@db_required
@pytest.mark.asyncio
async def test_create_and_list(auth_admin, clean_keys):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/admin/api-keys",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json={
                "provider": "openai",
                "label": "pytest-main",
                "api_key": "sk-pytest-1234567890",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provider"] == "openai"
        assert body["label"] == "pytest-main"
        # masked: never echo the raw key
        assert body["api_key_masked"] == "••••7890"
        assert "api_key" not in body

        r = await c.get("/admin/api-keys", cookies=auth_admin["cookies"])
        assert r.status_code == 200
        labels = {row["label"] for row in r.json()}
        assert "pytest-main" in labels


@db_required
@pytest.mark.asyncio
async def test_duplicate_label_returns_409(auth_admin, clean_keys):
    payload = {
        "provider": "openai",
        "label": "pytest-dup",
        "api_key": "sk-aaa",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/admin/api-keys",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json=payload,
        )
        assert r.status_code == 200
        r = await c.post(
            "/admin/api-keys",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json=payload,
        )
        assert r.status_code == 409


@db_required
@pytest.mark.asyncio
async def test_delete_blocked_when_referenced(auth_admin, clean_keys, db_session):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/admin/api-keys",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json={
                "provider": "openai",
                "label": "pytest-ref",
                "api_key": "sk-ref",
            },
        )
        assert r.status_code == 200
        key_id = r.json()["id"]

        # Reference the key from ai_steps.embedding so DELETE should be blocked.
        await db_session.execute(
            update(AiStep)
            .where(AiStep.step_key == "embedding")
            .values(api_key_id=key_id)
        )
        await db_session.commit()

        r = await c.delete(
            f"/admin/api-keys/{key_id}",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
        assert r.status_code == 409
        body = r.json()
        assert "embedding" in body["detail"]["referenced_by"]
