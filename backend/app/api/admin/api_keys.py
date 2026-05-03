import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.ai_step import AiStep
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyResponse, ApiKeyUpdate

router = APIRouter(
    prefix="/api-keys",
    tags=["admin", "api-keys"],
)


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(db: AsyncSession = Depends(get_db)) -> list[ApiKeyResponse]:
    rows = (
        await db.execute(select(ApiKey).order_by(ApiKey.provider, ApiKey.label))
    ).scalars().all()
    return [ApiKeyResponse.from_model(r) for r in rows]


@router.post("", response_model=ApiKeyResponse, status_code=status.HTTP_200_OK)
async def create_api_key(
    payload: ApiKeyCreate, db: AsyncSession = Depends(get_db)
) -> ApiKeyResponse:
    row = ApiKey(
        provider=payload.provider.strip().lower(),
        label=payload.label.strip(),
        api_key=payload.api_key,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="duplicate label for provider",
        )
    await db.refresh(row)
    return ApiKeyResponse.from_model(row)


@router.put("/{key_id}", response_model=ApiKeyResponse)
async def update_api_key(
    key_id: uuid.UUID,
    payload: ApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyResponse:
    row = await db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="api_key not found")
    data = payload.model_dump(exclude_unset=True)
    if "label" in data:
        row.label = data["label"].strip()
    if "api_key" in data:
        row.api_key = data["api_key"]
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="duplicate label for provider",
        )
    await db.refresh(row)
    return ApiKeyResponse.from_model(row)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    key_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    row = await db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="api_key not found")
    referencing = (
        await db.execute(
            select(AiStep.step_key).where(AiStep.api_key_id == key_id)
        )
    ).scalars().all()
    if referencing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "api_key in use by one or more ai_steps",
                "referenced_by": list(referencing),
            },
        )
    await db.delete(row)
    await db.commit()
