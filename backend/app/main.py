import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.api.admin_processing_stats import router as admin_processing_stats_router
from app.api.auth import me_router as me_router
from app.api.auth import router as auth_router
from app.schemas.errors import ErrorCode, ErrorResponse
from app.api.episodes import router as episodes_router
from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.qa_feedback import router as qa_feedback_router
from app.api.query import router as query_router
from app.api.queue import router as queue_router
from app.api.schedules import router as schedules_router
from app.api.settings import router as settings_router
from app.api.shows import router as shows_router
from app.api.shows import rss_preview_router
from app.api.stats import public_router as public_stats_router, router as stats_router
from app.api.transcripts import router as transcripts_router
from app.api.users import router as users_router
from app.core.config import settings
from app.core.csrf import CsrfAndOriginMiddleware

logger = logging.getLogger(__name__)


_WEB_REQUIRED_ENV = (
    ("GOOGLE_CLIENT_ID", "google_client_id"),
    ("GOOGLE_CLIENT_SECRET", "google_client_secret"),
    ("GOOGLE_REDIRECT_URI", "google_redirect_uri"),
    ("SESSION_SECRET", "session_secret"),
)


def _validate_web_env() -> None:
    missing: list[str] = []
    for env_name, attr in _WEB_REQUIRED_ENV:
        if not getattr(settings, attr):
            missing.append(env_name)
    if missing:
        for var in missing:
            logger.error("Web service requires %s but it is unset or empty", var)
        raise RuntimeError(
            "Web service requires "
            + ", ".join(missing)
            + " — set these environment variables on the backend service"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_web_env()
    yield


app = FastAPI(
    title="PodcastRAG API",
    version="0.1.0",
    lifespan=lifespan,
)


def _cors_headers_for(request: Request) -> dict[str, str]:
    """Manually compute CORS headers for error responses.

    Starlette's `ServerErrorMiddleware` sits outside `CORSMiddleware`, so any
    response produced by an exception_handler bypasses the CORS middleware.
    Without these headers the browser cannot read the body and shows
    "Failed to fetch" — exactly the bug this change fixes.
    """
    origin = request.headers.get("origin")
    if origin and origin in settings.frontend_origin_list:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return {}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception in %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": ErrorResponse(
                error_code=ErrorCode.INTERNAL_ERROR,
                provider=None,
                detail="Internal server error",
            ).model_dump()
        },
        headers=_cors_headers_for(request),
    )


# Order matters: middleware added LAST runs FIRST (outermost). We want
# CORSMiddleware outermost (so preflight OPTIONS short-circuits before CSRF),
# then CsrfAndOriginMiddleware. So we add CSRF first, then CORS.
app.add_middleware(CsrfAndOriginMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(me_router)
app.include_router(shows_router)
app.include_router(rss_preview_router)
app.include_router(schedules_router)
app.include_router(episodes_router)
app.include_router(transcripts_router)
app.include_router(query_router)
app.include_router(admin_router)
app.include_router(admin_processing_stats_router)
app.include_router(queue_router)
app.include_router(settings_router)
app.include_router(users_router)
app.include_router(stats_router)
app.include_router(public_stats_router)
from app.api.quota_requests import router as quota_requests_router  # noqa: E402
app.include_router(quota_requests_router)
app.include_router(qa_feedback_router)
app.include_router(events_router)

if settings.e2e_login_token:
    from app.api.auth_e2e import router as auth_e2e_router

    app.include_router(auth_e2e_router)
    logger.warning(
        "E2E_LOGIN_TOKEN is set — /auth/_e2e_login backdoor is ACTIVE"
    )


@app.get("/")
async def root() -> dict:
    return {"service": "PodcastRAG API", "status": "ok"}
