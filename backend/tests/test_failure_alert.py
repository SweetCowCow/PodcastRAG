"""task-failure-monitoring-and-circuit-breaker: failure_alert worker.

Scenarios:
1. 3 errors in 30 min → email sent + rows marked alerted_at
2. 2 errors in 30 min → no email
3. Already-alerted rows → no email
4. ZSend transient failure → rows stay un-alerted
5. ZSend not configured → log + skip + rows stay un-alerted

DB-dependent. Uses skipif pattern.
"""
from __future__ import annotations

import asyncio
import socket
from datetime import datetime, timedelta, timezone
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


async def _add_rows(task_name: str, n: int, *, alerted: bool = False):
    """Insert n rows quickly bypassing breaker logic."""
    from app.core.database import AsyncSessionFactory
    from app.models.task_failure_log import FailureType, TaskFailureLog

    now = datetime.now(timezone.utc)
    async with AsyncSessionFactory() as db:
        for i in range(n):
            row = TaskFailureLog(
                task_name=task_name,
                task_args_json=None,
                failure_type=FailureType.transient.value,
                error_class="TestErr",
                error_message=f"err {i}",
                provider_id="openai",
                retry_count=0,
                alerted_at=now if alerted else None,
            )
            db.add(row)
        await db.commit()


async def _count_unalerted(task_name: str) -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionFactory
    from app.models.task_failure_log import TaskFailureLog

    async with AsyncSessionFactory() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(TaskFailureLog)
                .where(
                    TaskFailureLog.task_name == task_name,
                    TaskFailureLog.alerted_at.is_(None),
                )
            )
        ).scalar_one()


async def test_three_errors_triggers_email(reset_log, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.zsend_api_key", "test-key", raising=False
    )
    monkeypatch.setattr(
        "app.core.config.settings.zsend_admin_to_email", "admin@example.com",
        raising=False,
    )
    await _add_rows("task.A", 3)
    with patch(
        "app.workers.failure_alert.send_failure_alert", return_value=None
    ) as mock_send:
        from app.workers.failure_alert import _run

        result = await _run()
    assert mock_send.await_count == 1 or mock_send.call_count == 1
    assert result["sent"] >= 1
    assert await _count_unalerted("task.A") == 0


async def test_two_errors_does_not_trigger(reset_log, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.zsend_api_key", "test-key", raising=False
    )
    monkeypatch.setattr(
        "app.core.config.settings.zsend_admin_to_email", "admin@example.com",
        raising=False,
    )
    await _add_rows("task.B", 2)
    with patch(
        "app.workers.failure_alert.send_failure_alert", return_value=None
    ) as mock_send:
        from app.workers.failure_alert import _run

        result = await _run()
    assert mock_send.await_count + mock_send.call_count == 0
    assert result["sent"] == 0
    assert await _count_unalerted("task.B") == 2


async def test_already_alerted_not_re_alerted(reset_log, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.zsend_api_key", "test-key", raising=False
    )
    monkeypatch.setattr(
        "app.core.config.settings.zsend_admin_to_email", "admin@example.com",
        raising=False,
    )
    await _add_rows("task.C", 3, alerted=True)
    with patch(
        "app.workers.failure_alert.send_failure_alert", return_value=None
    ) as mock_send:
        from app.workers.failure_alert import _run

        await _run()
    assert mock_send.await_count + mock_send.call_count == 0


async def test_zsend_failure_leaves_rows_unalerted(reset_log, monkeypatch):
    from app.services.zsend import ZSendError

    monkeypatch.setattr(
        "app.core.config.settings.zsend_api_key", "test-key", raising=False
    )
    monkeypatch.setattr(
        "app.core.config.settings.zsend_admin_to_email", "admin@example.com",
        raising=False,
    )
    await _add_rows("task.D", 3)
    with patch(
        "app.workers.failure_alert.send_failure_alert",
        side_effect=ZSendError("timeout", retryable=True),
    ):
        from app.workers.failure_alert import _run

        await _run()
    # All 3 still unalerted → next tick retries.
    assert await _count_unalerted("task.D") == 3


async def test_zsend_not_configured_skips(reset_log, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.zsend_api_key", None, raising=False
    )
    await _add_rows("task.E", 3)
    from app.workers.failure_alert import _run

    result = await _run()
    assert result.get("skipped") == "zsend_unconfigured"
    assert await _count_unalerted("task.E") == 3
