from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.ai_step import STEP_KEY_TO_TYPE, AiStep, StepKey, StepType
from app.models.api_key import ApiKey
from app.schemas.ai_step import (
    AiStepResponse,
    ChatStepUpdate,
    EmbeddingStepUpdate,
    WhisperApiStepUpdate,
    WhisperLocalStepUpdate,
)

router = APIRouter(
    prefix="/ai-steps",
    tags=["admin", "ai-steps"],
)


_VALID_KEYS = {k.value for k in StepKey}


@router.get("", response_model=list[AiStepResponse])
async def list_ai_steps(db: AsyncSession = Depends(get_db)) -> list[AiStepResponse]:
    # Always 5 rows; order by the canonical step_key sequence so the UI can
    # render sections in a stable order without sorting.
    canonical_order = [
        StepKey.answer.value,
        StepKey.rewrite.value,
        StepKey.summary.value,
        StepKey.embedding.value,
        StepKey.transcription.value,
    ]
    rows = (await db.execute(select(AiStep))).scalars().all()
    by_key = {r.step_key: r for r in rows}
    ordered = [by_key[k] for k in canonical_order if k in by_key]
    return [AiStepResponse.model_validate(r) for r in ordered]


@router.put("/{step_key}", response_model=AiStepResponse)
async def update_ai_step(
    step_key: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> AiStepResponse:
    if step_key not in _VALID_KEYS:
        raise HTTPException(status_code=404, detail="step_key not found")

    row = await db.get(AiStep, step_key)
    if row is None:
        raise HTTPException(status_code=404, detail="step_key not found")

    expected_type = STEP_KEY_TO_TYPE[StepKey(step_key)]

    # Pick the right pydantic schema for validation based on expected step_type
    # and (for whisper) the provider hint inside extra_config.
    try:
        if expected_type == StepType.chat:
            validated = ChatStepUpdate.model_validate(payload)
        elif expected_type == StepType.embedding:
            validated = EmbeddingStepUpdate.model_validate(payload)
        elif expected_type == StepType.whisper:
            extra = (payload or {}).get("extra_config") or {}
            provider = extra.get("provider")
            if provider == "openai":
                validated = WhisperApiStepUpdate.model_validate(payload)
            elif provider == "faster-whisper":
                validated = WhisperLocalStepUpdate.model_validate(payload)
            else:
                raise HTTPException(
                    status_code=422,
                    detail="extra_config.provider must be 'openai' or 'faster-whisper'",
                )
        else:  # pragma: no cover - exhausted by enum
            raise HTTPException(status_code=500, detail="unknown step_type")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    # Embedding-step provider restriction (D4). Backend enforcement so curl
    # cannot bypass the frontend's filtered dropdown.
    if expected_type == StepType.embedding:
        ak = await db.get(ApiKey, validated.api_key_id)
        if ak is None:
            raise HTTPException(status_code=422, detail="api_key not found")
        if ak.provider != "openai":
            raise HTTPException(
                status_code=422,
                detail="embedding step requires an openai-provider api_key",
            )

    # Apply the update. step_type is immutable; we never write it back.
    row.base_url = getattr(validated, "base_url", None)
    row.model = getattr(validated, "model", None)
    row.api_key_id = getattr(validated, "api_key_id", None)
    extra_obj = getattr(validated, "extra_config", None)
    row.extra_config = (
        extra_obj.model_dump() if hasattr(extra_obj, "model_dump") else (extra_obj or {})
    )

    await db.commit()
    await db.refresh(row)
    return AiStepResponse.model_validate(row)


@router.post("", status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
async def reject_create() -> None:
    raise HTTPException(status_code=405, detail="ai_steps cannot be created")


@router.delete("/{step_key}", status_code=status.HTTP_405_METHOD_NOT_ALLOWED)
async def reject_delete(step_key: str) -> None:
    raise HTTPException(status_code=405, detail="ai_steps cannot be deleted")
