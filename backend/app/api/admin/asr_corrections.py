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
    AsrCandidateApprove,
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
    source: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[AsrCorrectionResponse]:
    """List correction rules, newest first. Optional `source`
    (manual/llm) and `status` (pending/approved/rejected) filters power the
    admin UI's pending-candidate review section (source=llm&status=pending)."""
    stmt = select(AsrCorrectionTerm).order_by(
        AsrCorrectionTerm.created_at.desc()
    )
    if source is not None:
        stmt = stmt.where(AsrCorrectionTerm.source == source)
    if status is not None:
        stmt = stmt.where(AsrCorrectionTerm.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        AsrCorrectionResponse.model_validate(r, from_attributes=True) for r in rows
    ]


@router.post("/{term_id}/approve", response_model=AsrCorrectionResponse)
async def approve_candidate(
    term_id: uuid.UUID,
    payload: AsrCandidateApprove | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> AsrCorrectionResponse:
    """Approve a candidate: status='approved', enabled=true. Thereafter it is
    included in rule resolution (load_rules) and the second correction layer.

    EQ2c F3: an optional `correct` in the body overwrites the rule's correct-form
    before approving (fix a near-miss at approval time); omitted keeps the
    existing value. `wrong`/`scope`/`show_id` are never changed here."""
    row = await db.get(AsrCorrectionTerm, term_id)
    if row is None:
        raise HTTPException(status_code=404, detail="rule not found")
    if payload is not None and payload.correct is not None:
        row.correct = payload.correct
    row.status = "approved"
    row.enabled = True
    await db.commit()
    await db.refresh(row)
    return AsrCorrectionResponse.model_validate(row, from_attributes=True)


@router.post("/{term_id}/reject", response_model=AsrCorrectionResponse)
async def reject_candidate(
    term_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> AsrCorrectionResponse:
    """Reject a candidate: status='rejected', enabled=false. Kept (not deleted)
    so the detector's dedup skips re-proposing it."""
    row = await db.get(AsrCorrectionTerm, term_id)
    if row is None:
        raise HTTPException(status_code=404, detail="rule not found")
    row.status = "rejected"
    row.enabled = False
    await db.commit()
    await db.refresh(row)
    return AsrCorrectionResponse.model_validate(row, from_attributes=True)


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
