"""CSRF + Origin protection middleware (double-submit token pattern).

This middleware runs for every state-changing request (POST/PUT/PATCH/DELETE).
It rejects requests where:
  1. `Origin` header is missing or not in `FRONTEND_ORIGIN` allowlist
  2. `X-CSRF-Token` header is missing
  3. `X-CSRF-Token` header value does not match `csrf_token` cookie

GET / HEAD / OPTIONS are passed through (CORS preflight handled by CORSMiddleware).

Public endpoints (defined in `EXEMPT_PATHS`) bypass the check — they are not
authenticated and have no session, so no CSRF protection is meaningful.
"""

import hmac
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.schemas.errors import ErrorCode, ErrorResponse
from app.services.session_service import derive_csrf_token

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Endpoints that issue a session (callback) or do not require an authenticated
# session and therefore have no csrf_token cookie to double-submit.
EXEMPT_PATHS = {
    "/auth/google/start",
    "/auth/google/callback",
}

# Paths that still enforce the Origin allowlist (so cross-origin abuse stays
# blocked) but skip the CSRF double-submit check. sendBeacon and other
# fire-and-forget channels cannot set custom headers like X-CSRF-Token, so
# these endpoints rely on Origin + per-IP rate limit + strict payload
# validation as their protections.
ORIGIN_ONLY_PATHS = {
    "/events",
}

# Public endpoints that anonymous callers can hit. They have no session cookie
# so no CSRF check is meaningful; the IP rate limit + Origin header are the
# protections that remain.
EXEMPT_PATH_PATTERNS = [
    re.compile(r"^/shows/[0-9a-f-]{8,}/search/?$"),
]


def _error(request: Request, status_code: int, code: str, detail: str) -> JSONResponse:
    headers: dict[str, str] = {}
    origin = request.headers.get("origin")
    if origin and origin in settings.frontend_origin_list:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": ErrorResponse(
                error_code=code, provider=None, detail=detail
            ).model_dump()
        },
        headers=headers,
    )


class CsrfAndOriginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)
        if any(p.match(request.url.path) for p in EXEMPT_PATH_PATTERNS):
            return await call_next(request)

        # 1. Origin header check
        origin = request.headers.get("origin")
        if not origin:
            return _error(
                request,
                403,
                ErrorCode.ORIGIN_MISSING,
                "Origin header required for state-changing requests",
            )
        if origin not in settings.frontend_origin_list:
            return _error(
                request,
                403,
                ErrorCode.ORIGIN_FORBIDDEN,
                f"Origin {origin} is not allowed",
            )

        # Origin-only paths (e.g. /events fire-and-forget beacon) skip CSRF.
        if request.url.path in ORIGIN_ONLY_PATHS:
            return await call_next(request)

        # Fully anonymous requests (no session cookie) have nothing for CSRF
        # to protect — let the route's auth dependency surface a 401 instead
        # of a misleading 403 from us.
        if not request.cookies.get("session_id"):
            return await call_next(request)

        # 2. CSRF synchronizer-token (HMAC of session_id with SESSION_SECRET).
        #    Frontend gets the token from /me response body and echoes it as
        #    X-CSRF-Token. Cross-origin: backend cookie is not JS-readable on
        #    the frontend domain (different subdomain on PSL'd zeabur.app),
        #    so the previous "double-submit cookie" pattern can't work.
        csrf_header = request.headers.get("x-csrf-token")
        if not csrf_header:
            return _error(
                request,
                403,
                ErrorCode.CSRF_TOKEN_MISSING,
                "X-CSRF-Token header required",
            )
        session_id = request.cookies.get("session_id")
        if not session_id:
            return _error(
                request,
                403,
                ErrorCode.CSRF_TOKEN_INVALID,
                "CSRF token without session",
            )
        expected = derive_csrf_token(session_id)
        if not hmac.compare_digest(csrf_header.encode(), expected.encode()):
            return _error(
                request,
                403,
                ErrorCode.CSRF_TOKEN_INVALID,
                "CSRF token mismatch",
            )

        return await call_next(request)
