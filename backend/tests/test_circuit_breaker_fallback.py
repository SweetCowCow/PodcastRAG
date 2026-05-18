"""task-failure-monitoring-and-circuit-breaker: aihub→OpenAI fallback.

Scenarios:
1. ContentPolicyViolationError → fallback succeeds (one transient row)
2. BudgetExceededError → fallback succeeds (one transient row)
3. Both providers fail → two failure rows (aihub + openai)
4. openai direct provider failure does NOT fallback
5. Unknown model skips fallback

Plus a mapping table check.

DB-dependent for the failure_log writes; uses skipif pattern.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
import pytest_asyncio

from tests.conftest import _postgres_reachable


def _db_connectable() -> bool:
    if not _postgres_reachable():
        return False
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        from app.core.config import settings

        async def _check():
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.connect():
                    return True
            finally:
                await engine.dispose()

        return asyncio.run(_check())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_connectable(),
    reason="local postgres + valid DATABASE_URL credentials required",
)


@pytest_asyncio.fixture
async def reset_log():
    from sqlalchemy import delete

    from app.core.database import AsyncSessionFactory
    from app.models.task_failure_log import TaskFailureLog

    async with AsyncSessionFactory() as db:
        await db.execute(delete(TaskFailureLog))
        await db.commit()
    yield
    async with AsyncSessionFactory() as db:
        await db.execute(delete(TaskFailureLog))
        await db.commit()


def test_aihub_to_openai_mapping_table_matches_spec():
    from app.services.circuit_breaker import AIHUB_TO_OPENAI_MODEL_MAP

    assert AIHUB_TO_OPENAI_MODEL_MAP["gpt-5-mini"] == "gpt-4o-mini"
    assert AIHUB_TO_OPENAI_MODEL_MAP["gemini-2.5-flash-lite"] == "gpt-4o-mini"
    assert AIHUB_TO_OPENAI_MODEL_MAP["gpt-4o-mini"] == "gpt-4o-mini"
    assert AIHUB_TO_OPENAI_MODEL_MAP["gpt-4o"] == "gpt-4o"
    assert AIHUB_TO_OPENAI_MODEL_MAP["claude-haiku-4-5-20251001"] is None


async def _count_rows(provider: str | None = None, *, failure_type: str | None = None) -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionFactory
    from app.models.task_failure_log import TaskFailureLog

    async with AsyncSessionFactory() as db:
        stmt = select(func.count()).select_from(TaskFailureLog)
        if provider is not None:
            stmt = stmt.where(TaskFailureLog.provider_id == provider)
        if failure_type is not None:
            stmt = stmt.where(TaskFailureLog.failure_type == failure_type)
        return (await db.execute(stmt)).scalar_one()


async def test_content_policy_fallback_success(reset_log):
    from app.services.circuit_breaker import with_aihub_fallback
    from app.services.exceptions import ContentPolicyViolationError

    async def fake_call():
        raise ContentPolicyViolationError("blocked")

    with patch(
        "app.services.circuit_breaker.try_fallback",
        return_value=("ok-response", True),
    ):
        result, used = await with_aihub_fallback(
            fake_call,
            task_name="test.aihub",
            task_args=("ep1",),
            model="gemini-2.5-flash-lite",
            payload={"messages": [{"role": "user", "content": "hi"}]},
        )
    assert used is True
    assert result == "ok-response"
    # exactly one row, transient + recovered.
    assert await _count_rows("aihub", failure_type="transient") == 1
    assert await _count_rows("openai") == 0


async def test_budget_exceeded_fallback_success(reset_log):
    from app.services.circuit_breaker import with_aihub_fallback
    from app.services.exceptions import BudgetExceededError

    async def fake_call():
        raise BudgetExceededError("over budget")

    with patch(
        "app.services.circuit_breaker.try_fallback",
        return_value=("ok", True),
    ):
        _, used = await with_aihub_fallback(
            fake_call,
            task_name="test.aihub",
            task_args=("ep2",),
            model="gpt-5-mini",
            payload={"messages": []},
        )
    assert used is True


async def test_both_providers_fail_writes_two_rows(reset_log):
    from app.services.circuit_breaker import with_aihub_fallback
    from app.services.exceptions import ContentPolicyViolationError

    async def fake_call():
        raise ContentPolicyViolationError("blocked")

    with patch(
        "app.services.circuit_breaker.try_fallback",
        return_value=(None, False),
    ):
        with pytest.raises(ContentPolicyViolationError):
            await with_aihub_fallback(
                fake_call,
                task_name="test.aihub",
                task_args=("ep3",),
                model="gpt-4o-mini",
                payload={"messages": []},
            )
    assert await _count_rows("aihub") == 1
    assert await _count_rows("openai") == 1


async def test_openai_direct_failure_does_not_fallback(reset_log):
    """When the trigger exception type is raised but provider != aihub
    in the helper signature, we never call try_fallback."""
    from app.services.circuit_breaker import try_fallback

    resp, used = await try_fallback(
        "openai", payload={}, model="gpt-4o-mini"
    )
    assert used is False
    assert resp is None


async def test_unknown_model_skips_fallback(reset_log):
    """No mapping → with_aihub_fallback re-raises without fallback."""
    from app.services.circuit_breaker import with_aihub_fallback
    from app.services.exceptions import ContentPolicyViolationError

    async def fake_call():
        raise ContentPolicyViolationError("blocked")

    with pytest.raises(ContentPolicyViolationError):
        await with_aihub_fallback(
            fake_call,
            task_name="test.aihub",
            task_args=("ep4",),
            model="claude-haiku-4-5-20251001",
            payload={"messages": []},
        )
    # No failure log written because we never reached the write path.
    assert await _count_rows() == 0
