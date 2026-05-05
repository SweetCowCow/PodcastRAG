"""Generic client event ingestion.

R1.1 v1 supports a single event_type=`citation_click` from the QueryPage
SourceCard. Public endpoint with per-IP rate limit (60/min). Logged-in
sessions tag the row with user_id; anonymous rows store NULL.
"""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import check_ip_minute_limit, client_ip
from app.core.security import SESSION_COOKIE
from app.models.event import Event
from app.models.user import User, UserStatus
from app.schemas.event import EventCreate

router = APIRouter(prefix="/events", tags=["events"])

EVENTS_PER_MIN_LIMIT = 60


async def _resolve_optional_user(
    db: AsyncSession, session_id: str | None
) -> User | None:
    if not session_id:
        return None
    from sqlalchemy import select

    from app.services.session_service import resolve_session

    session_row = await resolve_session(db, session_id)
    if session_row is None:
        return None
    user = (
        await db.execute(select(User).where(User.id == session_row.user_id))
    ).scalar_one_or_none()
    if user is None or user.status == UserStatus.disabled.value:
        return None
    return user


@router.post("", status_code=202)
async def post_event(
    payload: EventCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    session_id: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Response:
    ip = client_ip(request)
    _count, exceeded = check_ip_minute_limit(
        ip, prefix="events", limit=EVENTS_PER_MIN_LIMIT
    )
    if exceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "ip_rate_limited",
                "detail": "events rate limit exceeded",
                "limit": EVENTS_PER_MIN_LIMIT,
            },
        )

    user = await _resolve_optional_user(db, session_id)

    row = Event(
        event_type=payload.event_type,
        event_payload=payload.payload.model_dump(),
        user_id=user.id if user is not None else None,
    )
    db.add(row)
    await db.commit()
    response.status_code = 202
    return response
