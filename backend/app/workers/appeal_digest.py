"""Daily digest of new account_appeals rows, emailed to admins via ZSend.

Runs once per day at 09:00 Asia/Taipei (= 01:00 UTC). Each run:
  1. Selects rows with ``notified_at IS NULL AND created_at >= now() - 25h``
  2. Composes a plain-text body (one line per appeal)
  3. Sends one email per recipient in ZSEND_ADMIN_TO_EMAIL
  4. Stamps ``notified_at`` on each row to avoid re-sending

Sibling to ``quota_digest`` — kept separate so each digest can evolve
independently (different cadence, different recipients in future).

When ZSEND_API_KEY is unset (e.g. ZSend not yet provisioned), the task
no-ops with a single info log line. ZSend transient errors trigger Celery
autoretry. Empty result-sets short-circuit without sending email.
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
from app.models.account_appeal import AccountAppeal
from app.services.zsend import ZSendError, send_email
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

LOOKBACK_HOURS = 25  # 1h overlap on top of the 24h cadence


@celery_app.task(
    name="app.workers.appeal_digest.send_appeal_digest",
    autoretry_for=(httpx.HTTPError, httpx.TimeoutException),
    max_retries=2,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def send_appeal_digest() -> dict:
    return asyncio.run(_run())


async def _run() -> dict:
    if not settings.zsend_api_key or not settings.zsend_admin_to_email:
        logger.info(
            "appeal_digest: ZSend not configured (api_key or admin_to_email "
            "missing) — skipping"
        )
        return {"skipped": "zsend_unconfigured"}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as db:
            stmt = (
                select(AccountAppeal)
                .where(
                    AccountAppeal.notified_at.is_(None),
                    AccountAppeal.created_at >= cutoff,
                )
                .order_by(AccountAppeal.created_at.asc())
            )
            rows = list((await db.execute(stmt)).scalars().all())

        if not rows:
            logger.info("appeal_digest: no new appeals to send")
            return {"sent_count": 0, "recipient_count": 0}

        body = _build_digest_body(rows)
        subject = f"[PodcastRAG] {len(rows)} 筆帳號申訴待處理"
        recipients = _parse_recipients(settings.zsend_admin_to_email)

        for to in recipients:
            try:
                await send_email(to, subject, body)
            except ZSendError as exc:
                if exc.retryable:
                    raise
                logger.warning(
                    "appeal_digest: non-retryable ZSend error for %s: %s",
                    to,
                    exc,
                )

        ids = [row.id for row in rows]
        async with Session() as db:
            await db.execute(
                update(AccountAppeal)
                .where(AccountAppeal.id.in_(ids))
                .values(notified_at=datetime.now(timezone.utc))
            )
            await db.commit()

        logger.info(
            "appeal_digest: sent to %d recipients covering %d rows",
            len(recipients),
            len(rows),
        )
        return {"sent_count": len(rows), "recipient_count": len(recipients)}
    finally:
        await engine.dispose()


def _build_digest_body(rows: list[AccountAppeal]) -> str:
    lines: list[str] = []
    lines.append(f"過去 24 小時內有 {len(rows)} 筆新申訴：\n")
    for i, row in enumerate(rows, start=1):
        truncated = (row.reason or "")[:200]
        if len(row.reason or "") > 200:
            truncated += "…"
        lines.append(
            f"{i}. {row.email}\n"
            f"   送出於：{row.created_at.isoformat()}\n"
            f"   IP：{row.client_ip or '(unknown)'}\n"
            f"   理由：{truncated}\n"
        )
    lines.append(
        "\n處理方式：登入 prod DB 直查 account_appeals 表，回覆後手動調整 users.status。"
    )
    return "\n".join(lines)


def _parse_recipients(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


# Beat schedule entry — registered by celery_app.py.
# 01:00 UTC = 09:00 Asia/Taipei. Celery beat runs UTC clock per celery_app.conf.
APPEAL_DIGEST_BEAT_SCHEDULE = {
    "appeal-digest": {
        "task": "app.workers.appeal_digest.send_appeal_digest",
        "schedule": crontab(minute=0, hour=1),
    }
}
