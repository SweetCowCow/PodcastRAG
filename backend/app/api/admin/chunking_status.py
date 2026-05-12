"""GET /admin/chunking-status — per-show v1/v2 description chunk breakdown.

Lets ops watch the `chunking-version-coexistence` rollout progress
without poking the DB directly. Returns one row per show with episode
count and chunk counts per chunking_version.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter()

_STATUS_SQL = text(
    """
    SELECT
        s.id::text AS show_id,
        s.title AS show_title,
        COUNT(DISTINCT e.id) AS episode_total,
        COALESCE(SUM(CASE WHEN d.chunking_version = 1 THEN 1 ELSE 0 END), 0)
            AS v1_chunks,
        COALESCE(SUM(CASE WHEN d.chunking_version = 2 THEN 1 ELSE 0 END), 0)
            AS v2_chunks,
        COUNT(DISTINCT CASE WHEN d.chunking_version = 2 THEN e.id END)
            AS episodes_with_v2
    FROM shows s
    JOIN episodes e ON e.show_id = s.id
    LEFT JOIN episode_description_chunks d ON d.episode_id = e.id
    GROUP BY s.id, s.title
    ORDER BY s.title
    """
)


@router.get("/chunking-status")
async def chunking_status(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(_STATUS_SQL)).mappings().all()
    shows = []
    for r in rows:
        ep_total = int(r["episode_total"])
        ep_with_v2 = int(r["episodes_with_v2"])
        shows.append(
            {
                "show_id": r["show_id"],
                "title": r["show_title"],
                "episode_total": ep_total,
                "v1_chunks": int(r["v1_chunks"]),
                "v2_chunks": int(r["v2_chunks"]),
                "episodes_with_v2": ep_with_v2,
                "rollout_progress": f"{ep_with_v2}/{ep_total}",
            }
        )
    return {"shows": shows}
