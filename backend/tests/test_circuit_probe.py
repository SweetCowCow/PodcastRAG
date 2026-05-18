"""task-failure-monitoring-and-circuit-breaker: circuit_probe worker.

Scenarios:
1. Successful probe closes open circuit + recovery email sent
2. Failed probe leaves circuit open, no email
3. Closed circuit is not probed

DB-dependent. Uses skipif pattern.
"""
from __future__ import annotations

import asyncio
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
async def reset_circuit():
    from sqlalchemy import text

    from app.core.database import AsyncSessionFactory
    from app.workers.lifecycle import _seed_service_circuit_state_async

    async def _reset():
        async with AsyncSessionFactory() as db:
            await db.execute(
                text(
                    "UPDATE service_circuit_state "
                    "SET state='closed', opened_at=NULL, paused_task_count=0, "
                    "    last_probe_at=NULL, last_probe_result=NULL"
                )
            )
            await db.commit()
        await _seed_service_circuit_state_async()

    await _reset()
    yield
    await _reset()


async def _force_open(provider_id: str = "openai", paused: int = 5):
    from sqlalchemy import update

    from app.core.database import AsyncSessionFactory
    from app.models.service_circuit_state import (
        CircuitState,
        ServiceCircuitState,
    )

    async with AsyncSessionFactory() as db:
        await db.execute(
            update(ServiceCircuitState)
            .where(ServiceCircuitState.provider_id == provider_id)
            .values(
                state=CircuitState.open.value,
                opened_at=datetime.now(timezone.utc) - timedelta(minutes=90),
                paused_task_count=paused,
            )
        )
        await db.commit()


async def _state(provider_id: str) -> str:
    from sqlalchemy import select

    from app.core.database import AsyncSessionFactory
    from app.models.service_circuit_state import ServiceCircuitState

    async with AsyncSessionFactory() as db:
        return (
            await db.execute(
                select(ServiceCircuitState.state).where(
                    ServiceCircuitState.provider_id == provider_id
                )
            )
        ).scalar_one()


async def test_successful_probe_closes_circuit(reset_circuit):
    await _force_open("openai", paused=12)
    with patch(
        "app.workers.circuit_probe._probe", return_value=True
    ), patch(
        "app.workers.circuit_probe.send_recovery_notice", return_value=None
    ) as mock_notice:
        from app.workers.circuit_probe import _run

        result = await _run()
    assert result["closed"] >= 1
    assert await _state("openai") == "closed"
    assert mock_notice.await_count + mock_notice.call_count == 1


async def test_failed_probe_maintains_open(reset_circuit):
    await _force_open("openai")
    with patch(
        "app.workers.circuit_probe._probe", return_value=False
    ), patch(
        "app.workers.circuit_probe.send_recovery_notice", return_value=None
    ) as mock_notice:
        from app.workers.circuit_probe import _run

        result = await _run()
    assert await _state("openai") == "open"
    assert result["failed"] >= 1
    assert mock_notice.await_count + mock_notice.call_count == 0


async def test_closed_circuits_not_probed(reset_circuit):
    # All three providers default closed → probe path should no-op.
    with patch("app.workers.circuit_probe._probe") as mock_probe:
        from app.workers.circuit_probe import _run

        result = await _run()
    assert result["probed"] == 0
    assert mock_probe.call_count == 0
