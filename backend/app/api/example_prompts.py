"""Per-show per-mode example-prompt endpoints.

Part of change `per-show-mode-example-prompts`.
- Public GET /shows/{show_id}/example-prompts → cold-start chip fallback.
- Admin POST backfill (single show runs inline; all shows enqueue Celery).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.show import Show
from app.models.show_example_prompt import ExamplePromptMode, ShowExamplePrompt
from app.services.example_prompts import generate_for_show

router = APIRouter()


@router.get("/shows/{show_id}/example-prompts")
async def get_example_prompts(
    show_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Public — return stored prompts grouped by mode, each ordered by ordinal.

    A show with no generated prompts returns the three keys each mapping to an
    empty array. Reading NEVER triggers LLM generation.
    """
    rows = (
        await db.execute(
            select(ShowExamplePrompt.mode, ShowExamplePrompt.question)
            .where(ShowExamplePrompt.show_id == show_id)
            .order_by(ShowExamplePrompt.mode, ShowExamplePrompt.ordinal)
        )
    ).all()
    out: dict[str, list[str]] = {m.value: [] for m in ExamplePromptMode}
    for mode, question in rows:
        key = mode.value if hasattr(mode, "value") else str(mode)
        out.setdefault(key, []).append(question)
    return out


@router.post(
    "/admin/shows/{show_id}/example-prompts/backfill",
    dependencies=[Depends(require_admin)],
)
async def backfill_one(
    show_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """Admin — (re)generate example prompts for a single show inline."""
    counts = await generate_for_show(db, show_id)
    return {"show_id": str(show_id), "counts": counts}


@router.post(
    "/admin/example-prompts/backfill-all",
    dependencies=[Depends(require_admin)],
)
async def backfill_all(db: AsyncSession = Depends(get_db)) -> dict:
    """Admin — enqueue background generation for every show (no inline LLM)."""
    show_ids = (await db.execute(select(Show.id))).scalars().all()
    # Local import avoids a circular import at module load (worker imports models).
    from app.workers.example_prompts_task import generate_show_example_prompts

    for sid in show_ids:
        generate_show_example_prompts.delay(str(sid))
    return {"enqueued": len(show_ids)}
