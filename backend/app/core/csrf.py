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

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.schemas.errors import ErrorCode, ErrorResponse

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Endpoints that issue a session (callback) or do not require an authenticated
# session and therefore have no csrf_token cookie to double-submit.
EXEMPT_PATHS = {
    "/auth/google/start",
    "/auth/google/callback",
}


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

        # 2. CSRF double-submit
        csrf_header = request.headers.get("x-csrf-token")
        csrf_cookie = request.cookies.get("csrf_token")
        if not csrf_header:
            return _error(
                request,
                403,
                ErrorCode.CSRF_TOKEN_MISSING,
                "X-CSRF-Token header required",
            )
        if not csrf_cookie or not hmac.compare_digest(
            csrf_header.encode(), csrf_cookie.encode()
        ):
            return _error(
                request,
                403,
                ErrorCode.CSRF_TOKEN_INVALID,
                "CSRF token mismatch",
            )

        return await call_next(request)
