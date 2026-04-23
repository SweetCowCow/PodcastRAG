from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.llm_config import LlmConfig
from app.schemas.admin import MASKED_API_KEY, LlmConfigResponse, LlmConfigUpdate
from app.services.llm_config import get_config, update_config

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
