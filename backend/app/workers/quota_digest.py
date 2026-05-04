"""Beat-driven digest of pending quota_requests, emailed to admins via ZSend.

Runs at UTC 09:00 and 21:00 (台北 17:00 + 隔日 05:00). Each run:
  1. Selects pending rows whose last_digest_at IS NULL or older than 6 hours
  2. Composes a plain-text summary
  3. Sends one email per recipient in ZSEND_ADMIN_TO_EMAIL
  4. Updates last_digest_at for the digested rows

When ZSEND_API_KEY is unset (e.g. ZSend not yet provisioned), the task
no-ops with a single info log line. ZSend transient errors trigger
Celery autoretry. Retry exhaustion still updates last_digest_at so the
next 12-hour cron does not re-send the same rows.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from celery.schedules import crontab
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.quota_request import QuotaRequest, QuotaRequestStatus
from app.models.user import User
from app.services.zsend import ZSendError, send_email
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

DIGEST_COOLDOWN_HOURS = 6
ADMIN_TAB_URL = "https://podcastrag.zeabur.app/admin/quota-requests"


@celery_app.task(
    name="app.workers.quota_digest.send_quota_digest",
    autoretry_for=(httpx.HTTPError, httpx.TimeoutException),
    max_retries=2,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def send_quota_digest() -> dict:
    return asyncio.run(_run())


async def _run() -> dict:
    if not settings.zsend_api_key or not settings.zsend_admin_to_email:
        logger.info(
            "quota_digest: ZSend not configured (api_key or admin_to_email missing) "
            "— skipping"
        )
        return {"skipped": "zsend_unconfigured"}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=DIGEST_COOLDOWN_HOURS)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as db:
            stmt = (
                select(QuotaRequest, User.email)
                .join(User, User.id == QuotaRequest.user_id)
                .where(
                    QuotaRequest.status == QuotaRequestStatus.pending.value,
                    (QuotaRequest.last_digest_at.is_(None))
                    | (QuotaRequest.last_digest_at < cutoff),
                )
                .order_by(QuotaRequest.requested_at.asc())
            )
            rows = (await db.execute(stmt)).all()

        if not rows:
            logger.info("quota_digest: no pending requests to send")
            return {"sent_count": 0, "recipient_count": 0}

        body = _build_digest_body(rows)
        subject = f"[PodcastRAG] {len(rows)} 筆 quota 申請待處理"
        recipients = _parse_recipients(settings.zsend_admin_to_email)

        # Send to each recipient. ZSendError(retryable=True) on first send
        # bubbles up — Celery autoretry covers it. Non-retryable ZSendError
        # we log and continue with the rest of the recipients (don't fail
        # the whole batch because one address is malformed).
        for to in recipients:
            try:
                await send_email(to, subject, body)
            except ZSendError as exc:
                if exc.retryable:
                    raise
                logger.warning(
                    "quota_digest: non-retryable ZSend error for %s: %s",
                    to,
                    exc,
                )

        # Update last_digest_at on all digested rows
        ids = [qr.id for qr, _email in rows]
        async with Session() as db:
            await db.execute(
                update(QuotaRequest)
                .where(QuotaRequest.id.in_(ids))
                .values(last_digest_at=datetime.now(timezone.utc))
            )
            await db.commit()

        logger.info(
            "quota_digest: sent to %d recipients covering %d rows",
            len(recipients),
            len(rows),
        )
        return {"sent_count": len(rows), "recipient_count": len(recipients)}
    finally:
        await engine.dispose()


def _build_digest_body(rows: list[tuple[QuotaRequest, str]]) -> str:
    lines: list[str] = []
    lines.append(f"目前有 {len(rows)} 筆 quota 申請等待處理：\n")
    now = datetime.now(timezone.utc)
    for i, (qr, email) in enumerate(rows, start=1):
        age = now - qr.requested_at
        age_hours = int(age.total_seconds() / 3600)
        lines.append(
            f"{i}. {email}\n"
            f"   送出於：{qr.requested_at.isoformat()}（{age_hours} 小時前）\n"
            f"   理由：{qr.reason}\n"
        )
    lines.append(f"\n後台處理：{ADMIN_TAB_URL}")
    return "\n".join(lines)


def _parse_recipients(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


# Beat schedule entry — registered by celery_app.py
QUOTA_DIGEST_BEAT_SCHEDULE = {
    "quota-digest": {
        "task": "app.workers.quota_digest.send_quota_digest",
        "schedule": crontab(minute=0, hour="9,21"),
    }
}
