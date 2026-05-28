"""Admin endpoint: `POST /admin/lexical-idf/refresh` — recompute IDF cache.

Part of change `retrieve-quality-step1-idf-and-prefilter` (Layer A,
Decision A4: IDF refresh 走 batch 不走 trigger).

Usage:
    POST /admin/lexical-idf/refresh?show_id=<uuid>   # one show
    POST /admin/lexical-idf/refresh?all=true         # every show
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.show import Show
from app.services.lexical_idf import refresh_freq_table

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/lexical-idf",
    tags=["admin-lexical-idf"],
    dependencies=[Depends(require_admin)],
)


@router.post("/refresh")
async def refresh_lexical_idf(
    show_id: uuid.UUID | None = Query(default=None),
    all: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not show_id and not all:
        raise HTTPException(
            status_code=400,
            detail="must pass either ?show_id=<uuid> or ?all=true",
        )

    if show_id:
        result = await refresh_freq_table(db, show_id)
        return {"status": "ok", "show_id": str(show_id), **result}

    show_ids = (await db.execute(select(Show.id))).scalars().all()
    results = []
    for sid in show_ids:
        try:
            r = await refresh_freq_table(db, sid)
            results.append({"show_id": str(sid), "status": "ok", **r})
        except Exception as exc:
            logger.exception("refresh_freq_table failed for show %s", sid)
            results.append({"show_id": str(sid), "status": "error", "error": str(exc)})
    return {"status": "ok", "shows": results}
