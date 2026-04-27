from fastapi import APIRouter, Depends
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.app_settings import AppSettings
from app.schemas.settings import AppSettingsOut, AppSettingsUpdate
from app.services.settings_cache import publish_max_concurrent

router = APIRouter(prefix="/admin/settings", tags=["settings"])

SINGLETON_ID = 1


async def _get_or_create(db: AsyncSession) -> AppSettings:
    """Read the singleton row, creating it with defaults if missing."""
    row = await db.get(AppSettings, SINGLETON_ID)
    if row is None:
        row = AppSettings(
            id=SINGLETON_ID,
            max_concurrent_transcriptions=1,
            monthly_cost_cap_usd=None,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
    return row


@router.get("", response_model=AppSettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)) -> AppSettingsOut:
    row = await _get_or_create(db)
    return AppSettingsOut.model_validate(row)


@router.put("", response_model=AppSettingsOut)
async def update_settings(
    payload: AppSettingsUpdate, db: AsyncSession = Depends(get_db)
) -> AppSettingsOut:
    provided = payload.model_dump(exclude_unset=True)

    insert_values = {
        "id": SINGLETON_ID,
        "max_concurrent_transcriptions": provided.get(
            "max_concurrent_transcriptions", 1
        ),
        "monthly_cost_cap_usd": provided.get("monthly_cost_cap_usd"),
    }
    stmt = pg_insert(AppSettings).values(**insert_values)
    if provided:
        stmt = stmt.on_conflict_do_update(
            index_elements=[AppSettings.id], set_=provided
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=[AppSettings.id])
    await db.execute(stmt)
    await db.flush()

    row = await db.get(AppSettings, SINGLETON_ID)
    await db.refresh(row)

    publish_max_concurrent(row.max_concurrent_transcriptions)

    return AppSettingsOut.model_validate(row)
