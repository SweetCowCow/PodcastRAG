"""task-failure-monitoring-and-circuit-breaker: admin REST endpoints.

Scenarios:
1. GET /admin/service-status returns 3 rows (after seed)
2. POST resume on open → 200, state closed, manual_resumed_by stamped
3. POST resume on already-closed → 409
4. Non-admin user → 403
"""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import _postgres_reachable

db_required = pytest.mark.skipif(
    not _postgres_reachable(), reason="local postgres not running"
)


@pytest_asyncio.fixture
async def reset_circuit_state():
    from sqlalchemy import text

    from app.core.database import AsyncSessionFactory
    from app.workers.lifecycle import _seed_service_circuit_state_async

    async def _reset():
        async with AsyncSessionFactory() as db:
            await db.execute(
                text(
                    "UPDATE service_circuit_state "
                    "SET state='closed', opened_at=NULL, paused_task_count=0, "
                    "    manual_resumed_by=NULL, manual_resumed_at=NULL"
                )
            )
            await db.commit()
        await _seed_service_circuit_state_async()

    await _reset()
    yield
    await _reset()


async def _force_open(provider_id: str = "openai"):
    from datetime import datetime, timezone

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
                opened_at=datetime.now(timezone.utc),
                paused_task_count=7,
            )
        )
        await db.commit()


@db_required
@pytest.mark.asyncio
async def test_get_service_status_returns_all_three(auth_admin, reset_circuit_state):
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/admin/service-status", cookies=auth_admin["cookies"]
        )
    assert r.status_code == 200, r.text
    body = r.json()
    pids = {row["provider_id"] for row in body}
    assert {"openai", "aihub", "zsend"} <= pids


@db_required
@pytest.mark.asyncio
async def test_post_resume_opens_to_closes(auth_admin, reset_circuit_state):
    from app.main import app

    await _force_open("openai")
    with patch(
        "app.api.admin_circuit.send_recovery_notice", return_value=None
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/admin/service-status/openai/resume",
                cookies=auth_admin["cookies"],
                headers=auth_admin["csrf_headers"],
            )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "closed"
    assert body["manual_resumed_by"] == auth_admin["user"].email
    assert body["manual_resumed_at"] is not None


@db_required
@pytest.mark.asyncio
async def test_post_resume_on_already_closed_returns_409(
    auth_admin, reset_circuit_state
):
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/admin/service-status/openai/resume",
            cookies=auth_admin["cookies"],
            headers=auth_admin["csrf_headers"],
        )
    assert r.status_code == 409, r.text


@db_required
@pytest.mark.asyncio
async def test_non_admin_gets_403(auth_member, reset_circuit_state):
    from app.main import app

    await _force_open("openai")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/admin/service-status/openai/resume",
            cookies=auth_member["cookies"],
            headers=auth_member["csrf_headers"],
        )
    assert r.status_code == 403
