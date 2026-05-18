"""Admin REST: list service circuit state + manual resume.

Part of `task-failure-monitoring-and-circuit-breaker`. Wired under
``/admin/service-status``.

- ``GET /admin/service-status`` — returns all rows in
  ``service_circuit_state`` sorted by provider_id.
- ``POST /admin/service-status/{provider_id}/resume`` — atomic open→closed
  transition + ``manual_resumed_by/at`` stamp. Returns 409 if already
  closed; 200 with updated row on success.

CSRF + admin role enforced via existing ``CsrfAndOriginMiddleware`` +
``require_admin`` dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.service_circuit_state import (
    CircuitState,
    ServiceCircuitState,
)
from app.models.user import User
from app.services import circuit_breaker
from app.services.zsend import send_recovery_notice

router = APIRouter(
    prefix="/admin/service-status",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _serialise(row: ServiceCircuitState) -> dict:
    return {
        "provider_id": row.provider_id,
        "task_type": row.task_type,
        "state": row.state,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "paused_task_count": row.paused_task_count,
        "last_probe_at": row.last_probe_at.isoformat()
        if row.last_probe_at
        else None,
        "last_probe_result": row.last_probe_result,
        "manual_resumed_by": row.manual_resumed_by,
        "manual_resumed_at": row.manual_resumed_at.isoformat()
        if row.manual_resumed_at
        else None,
    }


@router.get("")
async def list_service_status(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(
            select(ServiceCircuitState).order_by(
                ServiceCircuitState.provider_id
            )
        )
    ).scalars().all()
    return [_serialise(r) for r in rows]


@router.post("/{provider_id}/resume")
async def manual_resume(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict:
    # Snapshot existing row to get opened_at / paused_count for the
    # recovery notice email.
    snapshot = (
        await db.execute(
            select(ServiceCircuitState).where(
                ServiceCircuitState.provider_id == provider_id
            )
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown provider_id {provider_id!r}",
        )
    if snapshot.state != CircuitState.open.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="provider circuit is already closed",
        )
    opened_at = snapshot.opened_at
    paused_count = snapshot.paused_task_count or 0

    # Atomic open→closed via circuit_breaker service (uses a fresh engine
    # / its own transaction). Returns None if a concurrent action raced
    # and closed first.
    result = await circuit_breaker.close(
        provider_id, by=admin.email, kind="manual"
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="provider circuit is already closed",
        )

    # Best-effort recovery email (don't fail the API call on ZSend issues).
    try:
        await send_recovery_notice(
            provider_id=provider_id,
            opened_at=opened_at,
            closed_at=datetime.now(timezone.utc),
            paused_count=paused_count,
            kind="manual",
        )
    except Exception:
        pass

    # Re-read to return the updated snapshot.
    refreshed = (
        await db.execute(
            select(ServiceCircuitState).where(
                ServiceCircuitState.provider_id == provider_id
            )
        )
    ).scalar_one()
    return _serialise(refreshed)
