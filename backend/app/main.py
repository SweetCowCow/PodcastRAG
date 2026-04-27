from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await seed_llm_config_from_env()
    yield


app = FastAPI(
    title="PodcastRAG API",
    version="0.1.0",
    lifespan=lifespan,
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
