"""task-failure-monitoring-and-circuit-breaker: circuit breaker primitives.

Covers:
- 3rd permanent error opens (single transition + ZSend mock invoked)
- 2nd permanent error does NOT open
- Two concurrent 3rd-error workers → exactly one open transition

Needs local Postgres + the migration applied. Uses skipif pattern from
existing test_dispatcher_idempotency.py.
"""
from __future__ import annotations

import asyncio
import socket
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
async def reset_circuit():
    """Reset all 3 provider rows + clear failure log between tests."""
    from sqlalchemy import delete, text

    from app.core.database import AsyncSessionFactory
    from app.models.service_circuit_state import (
        CircuitState,
        ServiceCircuitState,
    )
    from app.models.task_failure_log import TaskFailureLog
    from app.workers.lifecycle import _seed_service_circuit_state_async

    async def _reset():
        async with AsyncSessionFactory() as db:
            await db.execute(delete(TaskFailureLog))
            await db.execute(
                text(
                    "UPDATE service_circuit_state "
                    "SET state='closed', opened_at=NULL, paused_task_count=0, "
                    "    last_probe_at=NULL, last_probe_result=NULL, "
                    "    manual_resumed_by=NULL, manual_resumed_at=NULL"
                )
            )
            await db.commit()
        await _seed_service_circuit_state_async()

    await _reset()
    yield
    await _reset()


async def _make_permanent_failure(provider_id: str = "openai"):
    """Write one permanent failure_log row + trigger breaker eval."""
    from app.services.failure_log import write_failure_log

    class _Exc(Exception):
        status_code = 402  # → permanent

    await write_failure_log(
        task_name="test.dummy",
        args=("x",),
        exc=_Exc("payment required"),
        provider_id=provider_id,
        retry_count=0,
    )


async def _state(provider_id: str = "openai") -> str:
    from sqlalchemy import select

    from app.core.database import AsyncSessionFactory
    from app.models.service_circuit_state import ServiceCircuitState

    async with AsyncSessionFactory() as db:
        row = (
            await db.execute(
                select(ServiceCircuitState.state).where(
                    ServiceCircuitState.provider_id == provider_id
                )
            )
        ).scalar_one()
        return row


async def test_third_permanent_error_opens_circuit(reset_circuit):
    with patch("app.services.failure_log.write_failure_log") as _unused:
        # Re-import the real function (patch above is just to avoid the
        # auto-applied async issue — actually we want the real one).
        pass

    with patch(
        "app.services.zsend.send_circuit_opened_alert", return_value=None
    ) as mock_send:
        await _make_permanent_failure()
        assert await _state() == "closed"
        await _make_permanent_failure()
        assert await _state() == "closed"
        await _make_permanent_failure()
        assert await _state() == "open"

        # ZSend was invoked exactly once on the transition.
        assert mock_send.await_count == 1 or mock_send.call_count == 1


async def test_two_errors_does_not_open(reset_circuit):
    with patch("app.services.zsend.send_circuit_opened_alert", return_value=None):
        await _make_permanent_failure()
        await _make_permanent_failure()
    assert await _state() == "closed"


async def test_concurrent_third_errors_yield_single_transition(reset_circuit):
    with patch(
        "app.services.zsend.send_circuit_opened_alert", return_value=None
    ) as mock_send:
        # Pre-seed 2 prior permanent errors so each concurrent call is "3rd".
        await _make_permanent_failure()
        await _make_permanent_failure()
        # Fire two concurrent "3rd" failures.
        await asyncio.gather(
            _make_permanent_failure(),
            _make_permanent_failure(),
        )
    assert await _state() == "open"
    # Despite 2 concurrent triggers, ZSend should fire exactly once thanks
    # to the atomic UPDATE ... WHERE state='closed' guard.
    total_calls = mock_send.await_count + mock_send.call_count
    # Use the larger of await/call count; depending on mock type only one is non-zero.
    assert max(mock_send.await_count, mock_send.call_count) == 1
