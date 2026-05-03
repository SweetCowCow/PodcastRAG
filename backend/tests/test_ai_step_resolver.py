"""Tests for services.ai_step_resolver."""

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from app.models.ai_step import AiStep
from app.models.api_key import ApiKey
from app.services.ai_step_resolver import (
    AiStepNotConfiguredError,
    get_step_config,
)
from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest_asyncio.fixture
async def fresh_steps(db_session):
    """Snapshot+restore ai_steps so resolver-specific writes don't leak."""
    snapshot = {
        r.step_key: (r.base_url, r.model, r.api_key_id, dict(r.extra_config or {}))
        for r in (await db_session.execute(select(AiStep))).scalars().all()
    }
    # null out pytest-* references to keep DELETE on api_keys safe
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
    yield
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
    for step_key, (base_url, model, api_key_id, extra_config) in snapshot.items():
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
async def test_chat_step_happy_path(db_session, fresh_steps):
    key = ApiKey(provider="openai", label="pytest-resolver", api_key="sk-resolver")
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)

    await db_session.execute(
        update(AiStep)
        .where(AiStep.step_key == "answer")
        .values(
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            api_key_id=key.id,
        )
    )
    await db_session.commit()

    cfg = await get_step_config(db_session, "answer")
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.api_key == "sk-resolver"
    assert cfg.model == "gpt-4o"
    assert cfg.step_type == "chat"


@db_required
@pytest.mark.asyncio
async def test_unknown_step_key_raises(db_session):
    with pytest.raises(AiStepNotConfiguredError):
        await get_step_config(db_session, "nonexistent")


@db_required
@pytest.mark.asyncio
async def test_chat_step_without_api_key_raises(db_session, fresh_steps):
    await db_session.execute(
        update(AiStep)
        .where(AiStep.step_key == "summary")
        .values(base_url="https://x", model="gpt-5-mini", api_key_id=None)
    )
    await db_session.commit()

    with pytest.raises(AiStepNotConfiguredError) as exc_info:
        await get_step_config(db_session, "summary")
    assert "api_key" in str(exc_info.value)


@db_required
@pytest.mark.asyncio
async def test_whisper_local_no_api_key_required(db_session, fresh_steps):
    await db_session.execute(
        update(AiStep)
        .where(AiStep.step_key == "transcription")
        .values(
            base_url=None,
            model="base",
            api_key_id=None,
            extra_config={"provider": "faster-whisper", "model_dir": "/tmp/m"},
        )
    )
    await db_session.commit()

    cfg = await get_step_config(db_session, "transcription")
    assert cfg.api_key is None
    assert cfg.extra_config["provider"] == "faster-whisper"
    assert cfg.extra_config["model_dir"] == "/tmp/m"


@db_required
@pytest.mark.asyncio
async def test_whisper_openai_requires_api_key(db_session, fresh_steps):
    await db_session.execute(
        update(AiStep)
        .where(AiStep.step_key == "transcription")
        .values(
            base_url=None,
            model=None,
            api_key_id=None,
            extra_config={"provider": "openai"},
        )
    )
    await db_session.commit()

    with pytest.raises(AiStepNotConfiguredError):
        await get_step_config(db_session, "transcription")
