"""Google OAuth + session management endpoints."""

import json
import logging

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    require_authenticated_user,
)
from app.models.user import User, UserStatus
from app.schemas.auth import LogoutResponse
from app.schemas.errors import ErrorCode, ErrorResponse
from app.schemas.user import UserOut
from app.services import google_oauth
from app.services.session_service import (
    create_session,
    delete_session,
)
from app.services.user_service import upsert_user_from_google

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])

OAUTH_STATE_COOKIE = "oauth_state"
OAUTH_STATE_MAX_AGE = 5 * 60  # 5 minutes
SESSION_MAX_AGE_SECONDS = settings.session_ttl_days * 24 * 3600

_serializer = URLSafeTimedSerializer(settings.session_secret, salt="oauth-state-v1")


def _err(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorResponse(
            error_code=code, provider=None, detail=detail
        ).model_dump(),
    )


def _set_session_cookies(
    resp: Response, session_token: str, csrf_token: str
) -> None:
    resp.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )
    resp.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=False,
        secure=True,
        samesite="none",
        path="/",
    )


def _clear_session_cookies(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path="/", samesite="none", secure=True)
    resp.delete_cookie(CSRF_COOKIE, path="/", samesite="none", secure=True)


def _frontend_redirect_target() -> str:
    origins = settings.frontend_origin_list
    if not origins:
        return "/"
    return origins[0]


@router.get("/google/start")
async def google_start() -> RedirectResponse:
    state = google_oauth.generate_state()
    code_verifier, code_challenge = google_oauth.generate_pkce_pair()

    payload = _serializer.dumps({"state": state, "code_verifier": code_verifier})

    auth_url = google_oauth.build_authorization_url(state, code_challenge)
    resp = RedirectResponse(auth_url, status_code=302)
    resp.set_cookie(
        OAUTH_STATE_COOKIE,
        payload,
        max_age=OAUTH_STATE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )
    return resp


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    oauth_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE),
) -> Response:
    if not code or not state:
        raise _err(400, ErrorCode.INVALID_OAUTH_STATE, "Missing code or state")
    if not oauth_state:
        raise _err(400, ErrorCode.INVALID_OAUTH_STATE, "Missing oauth state cookie")

    try:
        payload = _serializer.loads(oauth_state, max_age=OAUTH_STATE_MAX_AGE)
    except BadSignature:
        raise _err(400, ErrorCode.INVALID_OAUTH_STATE, "Invalid oauth state")

    if not isinstance(payload, dict) or payload.get("state") != state:
        raise _err(400, ErrorCode.INVALID_OAUTH_STATE, "State mismatch")

    code_verifier = payload.get("code_verifier")
    if not code_verifier:
        raise _err(400, ErrorCode.INVALID_OAUTH_STATE, "Missing code_verifier")

    try:
        token_data = await google_oauth.exchange_code(code, code_verifier)
    except httpx.HTTPError as exc:
        logger.exception("Google token exchange failed")
        raise _err(502, ErrorCode.LLM_UNAVAILABLE, f"Google token exchange failed: {exc}")

    access_token = token_data.get("access_token")
    if not access_token:
        raise _err(502, ErrorCode.INVALID_OAUTH_STATE, "No access_token from Google")

    try:
        info = await google_oauth.fetch_userinfo(access_token)
    except httpx.HTTPError as exc:
        logger.exception("Google userinfo fetch failed")
        raise _err(502, ErrorCode.LLM_UNAVAILABLE, f"Google userinfo fetch failed: {exc}")

    user = await upsert_user_from_google(db, info)
    if user.status == UserStatus.disabled.value:
        raise _err(403, ErrorCode.ACCOUNT_DISABLED, "Account is disabled")

    issued = await create_session(
        db,
        user_id=user.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    redirect_url = _frontend_redirect_target()
    resp = RedirectResponse(redirect_url, status_code=302)
    _set_session_cookies(resp, issued.session_token, issued.csrf_token)
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/", samesite="none", secure=True)
    return resp


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    db: AsyncSession = Depends(get_db),
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Response:
    if session_id:
        await delete_session(db, session_id)
    resp = JSONResponse({"ok": True})
    _clear_session_cookies(resp)
    return resp


@me_router.get("/me", response_model=UserOut)
async def me(user: User = Depends(require_authenticated_user)) -> UserOut:
    return UserOut.model_validate(user)
