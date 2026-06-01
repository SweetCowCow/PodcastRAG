from fastapi import APIRouter, Depends

from app.core.security import require_admin
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.transcript import Transcript, TranscriptStatus
from app.schemas.admin import QueueStatusResponse
from app.schemas.api_health import (
    ApiEntry,
    ApiHealthEvent,
    ExternalApiStatusResponse,
)
from app.services import api_health
from app.workers.throttle import GLOBAL_ACTIVE_KEY, _get_redis

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)

# Sub-routers (each carries its own /admin/... prefix).
from app.api.admin.ai_steps import router as ai_steps_router  # noqa: E402
from app.api.admin.api_keys import router as api_keys_router  # noqa: E402
from app.api.admin.asr_corrections import router as asr_corrections_router  # noqa: E402
from app.api.admin.chunking_status import router as chunking_status_router  # noqa: E402
from app.api.admin.diagnose_prefilter import router as diagnose_prefilter_router  # noqa: E402
from app.api.admin.episode_guests import router as episode_guests_router  # noqa: E402
from app.api.admin.eval_runs import router as eval_runs_router  # noqa: E402
from app.api.admin.rrf_sweep import router as rrf_sweep_router  # noqa: E402
from app.api.admin.summary_ops import router as summary_ops_router  # noqa: E402
from app.api.admin.quota_requests import router as quota_requests_router  # noqa: E402
from app.api.admin.tokenizer import router as tokenizer_router  # noqa: E402
from app.api.admin.topic_seg import router as topic_seg_router  # noqa: E402

router.include_router(api_keys_router)
router.include_router(ai_steps_router)
router.include_router(summary_ops_router)
router.include_router(quota_requests_router)
router.include_router(eval_runs_router)
router.include_router(rrf_sweep_router)
router.include_router(tokenizer_router)
router.include_router(asr_corrections_router)
router.include_router(topic_seg_router)
router.include_router(chunking_status_router)
router.include_router(diagnose_prefilter_router)
router.include_router(episode_guests_router)


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


