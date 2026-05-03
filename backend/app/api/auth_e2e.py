"""E2E login backdoor — env-gated, audit-logged.

This router is registered ONLY when E2E_LOGIN_TOKEN is set (see main.py).
When unregistered the path returns 404, indistinguishable from any unmapped path.
"""

import hmac
import logging
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _set_session_cookies
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.services.session_service import create_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth-e2e"])

E2E_SESSION_TTL = timedelta(minutes=15)
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_FAILURES = 5

# IP -> list of monotonic timestamps of recent failures
_failure_log: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is allowed; False if it should be throttled."""
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    failures = [t for t in _failure_log.get(ip, []) if t >= cutoff]
    _failure_log[ip] = failures
    return len(failures) <= RATE_LIMIT_MAX_FAILURES


def _record_failure(ip: str) -> None:
    _failure_log.setdefault(ip, []).append(time.monotonic())


def _reset_rate_limit() -> None:
    """Test helper — clear all failure history."""
    _failure_log.clear()


@router.get("/_e2e_login")
async def e2e_login(
    request: Request,
    token: str = "",
    db: AsyncSession = Depends(get_db),
) -> Response:
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    if not _check_rate_limit(ip):
        logger.warning(
            "e2e_login_rate_limited",
            extra={"event": "e2e_login_rate_limited", "ip": ip, "user_agent": user_agent},
        )
        raise HTTPException(status_code=429, detail="Too many failed attempts")

    expected = settings.e2e_login_token or ""
    if not token or not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        _record_failure(ip)
        logger.warning(
            "e2e_login_attempt",
            extra={
                "event": "e2e_login_attempt",
                "success": False,
                "ip": ip,
                "user_agent": user_agent,
            },
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    admin_emails = [e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()]
    if not admin_emails:
        logger.error("e2e_login: ADMIN_EMAILS is empty")
        raise HTTPException(status_code=500, detail="ADMIN_EMAILS not configured")
    target_email = admin_emails[0]

    result = await db.execute(select(User).where(User.email == target_email))
    user = result.scalar_one_or_none()
    if user is None:
        logger.error(
            "e2e_login: user not found for ADMIN_EMAILS[0]=%s — must SSO once first",
            target_email,
        )
        raise HTTPException(
            status_code=500,
            detail=f"User {target_email} not found — log in via Google SSO once to create the record",
        )

    issued = await create_session(
        db,
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
        ttl_override=E2E_SESSION_TTL,
    )

    logger.info(
        "e2e_login_attempt",
        extra={
            "event": "e2e_login_attempt",
            "success": True,
            "ip": ip,
            "user_agent": user_agent,
            "user_email": target_email,
        },
    )

    resp = RedirectResponse(url="/", status_code=302)
    _set_session_cookies(resp, issued.session_token, issued.csrf_token)
    return resp
