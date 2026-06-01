import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.asr_correction_term import AsrCorrectionTerm
from app.models.episode import Episode
from app.models.transcript import Transcript
from app.models.transcript_segment import TranscriptSegment
from app.models.user import User
from app.schemas.asr_correction import (
    AsrCorrectionCreate,
    AsrCorrectionPatch,
    AsrCorrectionResponse,
    BackfillRequest,
    BackfillResponse,
    MatchCountResponse,
)
from app.services import asr_correction

router = APIRouter(prefix="/asr-corrections", tags=["admin", "asr-corrections"])


@router.get("", response_model=list[AsrCorrectionResponse])
async def list_corrections(
    db: AsyncSession = Depends(get_db),
) -> list[AsrCorrectionResponse]:
    rows = (
        (
            await db.execute(
                select(AsrCorrectionTerm).order_by(
                    AsrCorrectionTerm.created_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        AsrCorrectionResponse.model_validate(r, from_attributes=True) for r in rows
    ]


@router.get("/match-count", response_model=MatchCountResponse)
async def match_count(
    wrong: str,
    scope: str = "global",
    show_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> MatchCountResponse:
    """Count existing segments whose text literally contains `wrong`, within
    scope. Powers the admin UI's pre-save over-broad-rule preview."""
    stmt = (
        select(func.count(TranscriptSegment.id))
        .select_from(TranscriptSegment)
        .join(Transcript, TranscriptSegment.transcript_id == Transcript.id)
        .join(Episode, Transcript.episode_id == Episode.id)
        .where(TranscriptSegment.text.contains(wrong, autoescape=True))
    )
    if scope == "show" and show_id is not None:
        stmt = stmt.where(Episode.show_id == show_id)
    n = await db.scalar(stmt)
    return MatchCountResponse(match_count=int(n or 0))


@router.post(
    "",
    response_model=AsrCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_correction(
    payload: AsrCorrectionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> AsrCorrectionResponse:
    row = AsrCorrectionTerm(
        wrong=payload.wrong,
        correct=payload.correct,
        scope=payload.scope,
        show_id=payload.show_id,
        note=payload.note,
        enabled=payload.enabled,
        created_by_user_id=user.id if user else None,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "duplicate_rule", "wrong": payload.wrong},
        )
    await db.refresh(row)
    return AsrCorrectionResponse.model_validate(row, from_attributes=True)


@router.patch("/{term_id}", response_model=AsrCorrectionResponse)
async def patch_correction(
    term_id: uuid.UUID,
    payload: AsrCorrectionPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> AsrCorrectionResponse:
    row = await db.get(AsrCorrectionTerm, term_id)
    if row is None:
        raise HTTPException(status_code=404, detail="rule not found")
    if payload.correct is not None:
        row.correct = payload.correct
    if payload.note is not None:
        row.note = payload.note
    if payload.enabled is not None:
        row.enabled = payload.enabled
    await db.commit()
    await db.refresh(row)
    return AsrCorrectionResponse.model_validate(row, from_attributes=True)


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_correction(
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> None:
    row = await db.get(AsrCorrectionTerm, term_id)
    if row is None:
        raise HTTPException(status_code=404, detail="rule not found")
    await db.delete(row)
    await db.commit()


@router.post("/backfill", response_model=BackfillResponse)
async def trigger_backfill(
    payload: BackfillRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> BackfillResponse:
    """`dry_run=true` (default) previews the impact + estimated cost without
    writing. `dry_run=false` enqueues the background backfill task and returns
    its task id."""
    if payload.dry_run:
        report = await asr_correction.backfill_corrections(
            db,
            show_id=payload.show_id,
            term_id=payload.term_id,
            dry_run=True,
        )
        return BackfillResponse(
            dry_run=True,
            affected_transcripts=report.affected_transcripts,
            affected_segments=report.affected_segments,
            affected_chunks=report.affected_chunks,
            estimated_cost_usd=report.estimated_cost_usd,
        )

    from app.workers.tasks import backfill_asr_corrections

    task = backfill_asr_corrections.delay(
        show_id=str(payload.show_id) if payload.show_id else None,
        term_id=str(payload.term_id) if payload.term_id else None,
    )
    return BackfillResponse(dry_run=False, task_id=task.id)
