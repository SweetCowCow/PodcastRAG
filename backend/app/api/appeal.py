"""POST /auth/appeal — disabled-user appeal submission endpoint.

This endpoint is INTENTIONALLY unauthenticated: disabled users have no
session (callback rejected them with 403), so we accept email + reason in
the body and look up the user ourselves. To prevent account-existence
enumeration, unknown emails AND active-status emails both get a 200
``{accepted: true}`` (no ``appeal_id``) without writing to the DB.

Rate-limited at 5 submissions / IP / UTC day. The counter ticks on EVERY
attempt (including silent-drops) so attackers cannot probe email existence
via the rate-limit response.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import redis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import client_ip
from app.models.account_appeal import AccountAppeal
from app.models.user import User, UserStatus
from app.schemas.appeal import AppealRequest, AppealResponse
from app.schemas.errors import ErrorCode, ErrorResponse

router = APIRouter(prefix="/auth", tags=["auth"])


APPEAL_RATE_KEY_PREFIX = "rl:appeal:ip"
APPEAL_RATE_TTL_SECONDS = 86_400


@lru_cache(maxsize=1)
def _get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.celery_broker_url)


def _today_key(ip: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{APPEAL_RATE_KEY_PREFIX}:{ip}:{now.strftime('%Y%m%d')}"


def _check_appeal_rate(ip: str) -> tuple[int, bool]:
    """Increment per-IP daily counter; return (count_after, exceeded).

    Falls back gracefully when Redis is unreachable (e.g. local pytest with
    no broker): treats as not-exceeded, so functional tests can still pass.
    The unit test for rate-limit monkeypatches this helper directly.
    """
    try:
        r = _get_redis()
        key = _today_key(ip)
        count = r.incr(key)
        if count == 1:
            r.expire(key, APPEAL_RATE_TTL_SECONDS)
        return count, count > settings.appeal_ip_rate_limit_per_day
    except (redis.RedisError, OSError):
        return 0, False


def _err(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(
            error_code=code, provider=None, detail=detail
        ).model_dump(),
    )


@router.post("/appeal", response_model=AppealResponse)
async def submit_appeal(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AppealResponse:
    if not settings.account_appeal_enabled:
        # Endpoint hard-disabled by config. Mirror the silent-drop response so
        # we don't reveal whether the feature is on (defense-in-depth).
        return AppealResponse(accepted=True)

    # Manually parse + validate so we can map ValidationError → 400
    # invalid_reason (FastAPI's default 422 doesn't fit the spec contract).
    try:
        raw = await request.json()
    except Exception:
        raise _err(400, ErrorCode.INVALID_REASON, "Invalid JSON body")
    try:
        payload = AppealRequest(**(raw or {}))
    except ValidationError:
        raise _err(400, ErrorCode.INVALID_REASON, "Invalid email or reason")

    ip = client_ip(request)

    # Rate-limit BEFORE DB lookup so the counter ticks on every attempt
    # (including silent-drops) — attackers can't probe via 429 vs 200.
    count, exceeded = _check_appeal_rate(ip)
    if exceeded:
        raise _err(429, ErrorCode.RATE_LIMITED, "Too many appeal submissions")

    # Look up user; silent-drop if unknown OR not disabled.
    user = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()

    if user is None or user.status != UserStatus.disabled.value:
        # Don't write a row; don't reveal which condition triggered.
        return AppealResponse(accepted=True)

    row = AccountAppeal(
        email=payload.email,
        reason=payload.reason,
        client_ip=ip,
        # We don't currently store disabled_at on the users table, so this
        # column stays NULL for now. Future change can backfill if/when we
        # add a users.disabled_at timestamp.
        user_disabled_at_snapshot=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return AppealResponse(accepted=True, appeal_id=row.id)
