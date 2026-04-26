from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.llm_config import LlmConfig
from app.models.transcript import Transcript, TranscriptStatus
from app.schemas.admin import (
    MASKED_API_KEY,
    LlmConfigResponse,
    LlmConfigUpdate,
    QueueStatusResponse,
)
from app.schemas.api_health import (
    ApiEntry,
    ApiHealthEvent,
    ExternalApiStatusResponse,
)
from app.services import api_health
from app.services.llm_config import get_config, update_config
from app.workers.throttle import GLOBAL_ACTIVE_KEY, _get_redis

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/llm-config", response_model=LlmConfigResponse)
async def read_llm_config(db: AsyncSession = Depends(get_db)) -> LlmConfigResponse:
    cfg = await get_config(db)
    return _mask(cfg)


@router.put("/llm-config", response_model=LlmConfigResponse)
async def write_llm_config(
    payload: LlmConfigUpdate, db: AsyncSession = Depends(get_db)
) -> LlmConfigResponse:
    cfg = await update_config(db, payload.model_dump(exclude_unset=True))
    return _mask(cfg)


@router.get("/queue-status", response_model=QueueStatusResponse)
async def queue_status(db: AsyncSession = Depends(get_db)) -> QueueStatusResponse:
    redis_client = _get_redis()
    active = int(redis_client.get(GLOBAL_ACTIVE_KEY) or 0)
    pending_in_queue = int(redis_client.llen("celery") or 0)
    pending_in_db = int(
        await db.scalar(
            select(func.count(Transcript.id)).where(
                Transcript.status == TranscriptStatus.pending
            )
        )
        or 0
    )
    return QueueStatusResponse(
        active=active,
        pending_in_queue=pending_in_queue,
        pending_in_db=pending_in_db,
        max_concurrent=settings.max_concurrent_transcriptions,
    )


@router.get(
    "/external-api-status", response_model=ExternalApiStatusResponse
)
async def external_api_status() -> ExternalApiStatusResponse:
    entries: list[ApiEntry] = []
    for name in api_health.API_NAMES:
        events_raw, degraded = api_health.get_recent(name, api_health.MAX_EVENTS)
        events = [ApiHealthEvent(**e) for e in events_raw]
        entries.append(
            ApiEntry(
                name=name,
                latest=events[0] if events else None,
                recent=events,
                degraded=degraded,
            )
        )
    return ExternalApiStatusResponse(apis=entries)


def _mask(cfg: LlmConfig) -> LlmConfigResponse:
    return LlmConfigResponse(
        answer_base_url=cfg.answer_base_url,
        answer_api_key=MASKED_API_KEY,
        answer_model=cfg.answer_model,
        rewrite_base_url=cfg.rewrite_base_url,
        rewrite_api_key=MASKED_API_KEY,
        rewrite_model=cfg.rewrite_model,
        updated_at=cfg.updated_at,
    )
