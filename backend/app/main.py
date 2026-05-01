import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.admin import router as admin_router
from app.schemas.errors import ErrorCode, ErrorResponse
from app.api.episodes import router as episodes_router
from app.api.health import router as health_router
from app.api.query import router as query_router
from app.api.queue import router as queue_router
from app.api.schedules import router as schedules_router
from app.api.settings import router as settings_router
from app.api.shows import router as shows_router
from app.api.shows import rss_preview_router
from app.api.transcripts import router as transcripts_router
from app.core.bootstrap import seed_llm_config_from_env
from app.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_llm_config_from_env()
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
    if origin and origin == settings.frontend_origin:
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(shows_router)
app.include_router(rss_preview_router)
app.include_router(schedules_router)
app.include_router(episodes_router)
app.include_router(transcripts_router)
app.include_router(query_router)
app.include_router(admin_router)
app.include_router(queue_router)
app.include_router(settings_router)


@app.get("/")
async def root() -> dict:
    return {"service": "PodcastRAG API", "status": "ok"}
