"""Tests for /admin/ai-steps."""

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
async def seeded_keys(db_session):
    """Snapshot ai_steps; insert one OpenAI key + one Anthropic key; restore."""
    snapshot_steps = {
        r.step_key: (r.base_url, r.model, r.api_key_id, dict(r.extra_config or {}))
        for r in (await db_session.execute(select(AiStep))).scalars().all()
    }

    # Make sure no leftover pytest keys are referenced by ai_steps.
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

    openai_key = ApiKey(provider="openai", label="pytest-openai", api_key="sk-o")
    anthro_key = ApiKey(
        provider="anthropic", label="pytest-anthropic", api_key="sk-a"
    )
    db_session.add_all([openai_key, anthro_key])
    await db_session.commit()
    await db_session.refresh(openai_key)
    await db_session.refresh(anthro_key)

    yield {"openai": openai_key, "anthropic": anthro_key}

    # Restore: detach pytest keys from ai_steps, delete keys, restore snapshot.
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
    for step_key, (base_url, model, api_key_id, extra_config) in snapshot_steps.items():
        await db_session.execute(
            update(AiStep)
            .where(AiStep.step_key == step_key)
            .values(
                base_url=base_url,
                model=model,
                api_key_id=api_key_id,
                extra_config=extra_config,
            )
        )
    await db_session.commit()


@db_required
@pytest.mark.asyncio
async def test_list_returns_five_rows_in_canonical_order(auth_admin):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/admin/ai-steps", cookies=auth_admin["cookies"])
        assert r.status_code == 200
        body = r.json()
        assert [row["step_key"] for row in body] == [
            "answer",
            "rewrite",
            "summary",
            "embedding",
            "transcription",
        ]
        # step_type assignment
        types = {row["step_key"]: row["step_type"] for row in body}
        assert types == {
            "answer": "chat",
            "rewrite": "chat",
            "summary": "chat",
            "embedding": "embedding",
            "transcription": "whisper",
        }


@db_required
@pytest.mark.asyncio
async def test_post_returns_405(auth_admin):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/admin/ai-steps",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
        assert r.status_code == 405


@db_required
@pytest.mark.asyncio
async def test_put_unknown_step_key_404(auth_admin):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.put(
            "/admin/ai-steps/foo",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json={
                "step_type": "chat",
                "base_url": "https://x",
                "model": "x",
                "api_key_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert r.status_code == 404


@db_required
@pytest.mark.asyncio
async def test_put_chat_step_succeeds(auth_admin, seeded_keys):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.put(
            "/admin/ai-steps/answer",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json={
                "step_type": "chat",
                "base_url": "https://hnd1.aihub.zeabur.ai/v1",
                "model": "gpt-4o",
                "api_key_id": str(seeded_keys["anthropic"].id),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["base_url"] == "https://hnd1.aihub.zeabur.ai/v1"
        assert body["model"] == "gpt-4o"


@db_required
@pytest.mark.asyncio
async def test_embedding_rejects_non_openai_provider(auth_admin, seeded_keys):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.put(
            "/admin/ai-steps/embedding",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json={
                "step_type": "embedding",
                "base_url": "https://api.openai.com/v1",
                "model": "text-embedding-3-small",
                "api_key_id": str(seeded_keys["anthropic"].id),
            },
        )
        assert r.status_code == 422
        assert "openai" in str(r.json()["detail"]).lower()


@db_required
@pytest.mark.asyncio
async def test_embedding_accepts_openai_provider(auth_admin, seeded_keys):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.put(
            "/admin/ai-steps/embedding",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json={
                "step_type": "embedding",
                "base_url": "https://api.openai.com/v1",
                "model": "text-embedding-3-small",
                "api_key_id": str(seeded_keys["openai"].id),
            },
        )
        assert r.status_code == 200, r.text


@db_required
@pytest.mark.asyncio
async def test_whisper_local_no_api_key_required(auth_admin, seeded_keys):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.put(
            "/admin/ai-steps/transcription",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
            json={
                "step_type": "whisper",
                "base_url": None,
                "model": "base",
                "api_key_id": None,
                "extra_config": {
                    "provider": "faster-whisper",
                    "model_dir": "/models/faster-whisper",
                },
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["api_key_id"] is None
        assert body["extra_config"]["provider"] == "faster-whisper"
