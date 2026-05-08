import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.tokenizer_term import TokenizerCustomTerm
from app.models.user import User
from app.schemas.tokenizer import (
    TokenizerTermCreate,
    TokenizerTermPatch,
    TokenizerTermResponse,
)
from app.services import tokenizer

router = APIRouter(prefix="/tokenizer", tags=["admin", "tokenizer"])


@router.get("/terms", response_model=list[TokenizerTermResponse])
async def list_terms(
    db: AsyncSession = Depends(get_db),
) -> list[TokenizerTermResponse]:
    rows = (
        await db.execute(
            select(TokenizerCustomTerm).order_by(
                TokenizerCustomTerm.created_at.desc()
            )
        )
    ).scalars().all()
    return [TokenizerTermResponse.model_validate(r, from_attributes=True) for r in rows]


@router.post(
    "/terms",
    response_model=TokenizerTermResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_term(
    payload: TokenizerTermCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> TokenizerTermResponse:
    row = TokenizerCustomTerm(
        term=payload.term.strip(),
        weight=payload.weight,
        source="manual",
        is_show_name=payload.is_show_name,
        created_by_user_id=user.id if user else None,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "duplicate_term", "term": payload.term},
        )
    await db.refresh(row)
    return TokenizerTermResponse.model_validate(row, from_attributes=True)


@router.patch("/terms/{term_id}", response_model=TokenizerTermResponse)
async def patch_term(
    term_id: uuid.UUID,
    payload: TokenizerTermPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> TokenizerTermResponse:
    row = await db.get(TokenizerCustomTerm, term_id)
    if row is None:
        raise HTTPException(status_code=404, detail="term not found")
    row.is_show_name = payload.is_show_name
    await db.commit()
    await db.refresh(row)
    return TokenizerTermResponse.model_validate(row, from_attributes=True)


@router.delete("/terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_term(
    term_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    row = await db.get(TokenizerCustomTerm, term_id)
    if row is None:
        raise HTTPException(status_code=404, detail="term not found")
    await db.delete(row)
    await db.commit()


@router.post("/reload", status_code=status.HTTP_202_ACCEPTED)
async def reload_terms(db: AsyncSession = Depends(get_db)) -> Response:
    """Reload the dictionary in the local process and broadcast to workers."""
    await tokenizer.reload_dictionary(db)
    try:
        from app.workers.tokenizer_reload import broadcast_reload

        broadcast_reload.delay()
    except Exception:
        # Workers may not be reachable in tests; the local reload is enough.
        pass
    return Response(status_code=status.HTTP_202_ACCEPTED)
