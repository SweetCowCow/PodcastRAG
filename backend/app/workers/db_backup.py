"""Daily off-site DB backup beat task.

Pipeline (streaming, no plaintext on disk):
    pg_dump --format=custom → age --encrypt → R2 upload_fileobj

Promotes the daily artifact to weekly/ on Sundays and monthly/ on day 1.
Surfaces failures + size anomalies via ZSend.

Env vars consumed (all `R2_BACKUP_*` to avoid colliding with the audio bucket
vars in `app.services.storage`):
    R2_BACKUP_ENDPOINT_URL
    R2_BACKUP_ACCESS_KEY_ID
    R2_BACKUP_SECRET_ACCESS_KEY
    R2_BACKUP_BUCKET
    BACKUP_AGE_PUBLIC_KEY  (comma-separated: admin recipient + GHA recipient)
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from datetime import datetime, timedelta, timezone

import httpx
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.services.r2_backup_client import (
    apply_lifecycle_policy,
    get_r2_backup_client,
    parse_recipients,
)
from app.services.zsend import ZSendError, send_email
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

SIZE_RATIO_LOW = 0.5
SIZE_RATIO_HIGH = 2.0
STDERR_TRUNCATE_CHARS = 2000


@celery_app.task(
    name="app.workers.db_backup.run_db_backup",
    autoretry_for=(httpx.HTTPError, BotoCoreError),
    max_retries=2,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def run_db_backup() -> dict:
    return asyncio.run(_run())


async def _run() -> dict:
    today = datetime.now(timezone.utc).date()
    today_key = f"daily/{today.isoformat()}.dump.age"

    client = get_r2_backup_client()
    if client is None:
        logger.warning(
            "db_backup: R2 backup not configured (R2_BACKUP_* env missing) — skipping"
        )
        return {"skipped": "r2_unconfigured"}

    public_keys = parse_recipients(settings.backup_age_public_key)
    if not public_keys:
        msg = "db_backup: BACKUP_AGE_PUBLIC_KEY missing — refusing to back up unencrypted"
        await _alert(
            f"[PodcastRAG] DB backup FAILED {today.isoformat()}",
            msg,
        )
        raise RuntimeError(msg)

    bucket = settings.r2_backup_bucket
    assert bucket  # mypy: get_r2_backup_client guarantees this

    # Idempotent — re-applying same rules is a no-op state-wise.
    try:
        apply_lifecycle_policy(client, bucket)
    except (BotoCoreError, ClientError):
        logger.exception("db_backup: lifecycle policy apply failed (continuing)")

    started = time.monotonic()
    try:
        size_bytes = _stream_backup_to_r2(client, bucket, today_key, public_keys)
    except BaseException as exc:  # noqa: BLE001 — surface every failure
        body = (
            f"DB backup failed on {today.isoformat()}.\n\n"
            f"Error: {type(exc).__name__}: {str(exc)[:STDERR_TRUNCATE_CHARS]}"
        )
        try:
            await _alert(
                f"[PodcastRAG] DB backup FAILED {today.isoformat()}",
                body,
            )
        except Exception:  # noqa: BLE001
            logger.exception("db_backup: alert dispatch failed (re-raising original)")
        raise

    duration_ms = int((time.monotonic() - started) * 1000)

    # Sunday → weekly promotion (weekday() == 6 is Sunday).
    if datetime.now(timezone.utc).weekday() == 6:
        weekly_key = f"weekly/{today.isoformat()}.dump.age"
        client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": today_key},
            Key=weekly_key,
        )
        logger.info("db_backup: promoted to weekly key=%s", weekly_key)

    # Day 1 → monthly promotion.
    if datetime.now(timezone.utc).day == 1:
        monthly_key = f"monthly/{today.isoformat()}.dump.age"
        client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": today_key},
            Key=monthly_key,
        )
        logger.info("db_backup: promoted to monthly key=%s", monthly_key)

    # Size-anomaly check vs yesterday's daily artifact.
    await _check_size_anomaly(client, bucket, today, size_bytes)

    logger.info(
        "db_backup: success key=%s size_bytes=%d duration_ms=%d",
        today_key,
        size_bytes,
        duration_ms,
    )
    return {
        "sent_count": 1,
        "size_bytes": size_bytes,
        "duration_ms": duration_ms,
        "key": today_key,
    }


def _stream_backup_to_r2(
    client, bucket: str, key: str, public_keys: list[str]
) -> int:
    """pg_dump | age --encrypt | upload_fileobj. Returns ciphertext byte count.

    No plaintext is ever written to disk — the dump bytes flow pg_dump.stdout
    → age.stdin → age.stdout → boto3 multipart upload buffer.
    """
    db_url = _libpq_url(settings.database_url)

    age_cmd = ["age", "--encrypt"]
    for pk in public_keys:
        age_cmd.extend(["--recipient", pk])

    pg_dump = subprocess.Popen(
        [
            "pg_dump",
            "--format=custom",
            "--compress=9",
            "--no-acl",
            "--no-owner",
            db_url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        age_proc = subprocess.Popen(
            age_cmd,
            stdin=pg_dump.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except BaseException:
        pg_dump.kill()
        pg_dump.wait()
        raise

    # Drop our handle so pg_dump receives SIGPIPE if age exits early.
    assert pg_dump.stdout is not None
    pg_dump.stdout.close()

    counter = _ByteCountingReader(age_proc.stdout)
    upload_exc: BaseException | None = None
    try:
        client.upload_fileobj(counter, bucket, key)
    except BaseException as exc:  # noqa: BLE001
        upload_exc = exc
        # Kill the upstream pipe so wait() returns; otherwise pg_dump may block on writes.
        age_proc.kill()
        pg_dump.kill()

    pg_rc = pg_dump.wait()
    age_rc = age_proc.wait()

    if upload_exc is not None:
        raise upload_exc

    if pg_rc != 0:
        stderr = (pg_dump.stderr.read() or b"").decode("utf-8", errors="replace")
        raise RuntimeError(
            f"pg_dump exited rc={pg_rc}: {stderr[:STDERR_TRUNCATE_CHARS]}"
        )
    if age_rc != 0:
        stderr = (age_proc.stderr.read() or b"").decode("utf-8", errors="replace")
        raise RuntimeError(
            f"age exited rc={age_rc}: {stderr[:STDERR_TRUNCATE_CHARS]}"
        )

    return counter.bytes_read


async def _check_size_anomaly(client, bucket: str, today, size_bytes: int) -> None:
    yesterday = today - timedelta(days=1)
    yesterday_key = f"daily/{yesterday.isoformat()}.dump.age"
    try:
        head = client.head_object(Bucket=bucket, Key=yesterday_key)
    except ClientError as exc:
        # Most commonly 404 NoSuchKey on first run — nothing to compare against.
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return
        logger.warning("db_backup: head_object failed for %s: %s", yesterday_key, exc)
        return

    prev_size = int(head.get("ContentLength", 0))
    if prev_size <= 0:
        return

    ratio = size_bytes / prev_size
    if SIZE_RATIO_LOW <= ratio <= SIZE_RATIO_HIGH:
        return

    logger.warning(
        "db_backup: size anomaly today=%d yesterday=%d ratio=%.2f",
        size_bytes,
        prev_size,
        ratio,
    )
    body = (
        f"Today's backup size deviates from yesterday's by ratio {ratio:.2f}x.\n\n"
        f"Today    ({today.isoformat()}): {size_bytes:,} bytes\n"
        f"Yesterday ({yesterday.isoformat()}): {prev_size:,} bytes\n\n"
        f"The artifact was uploaded as usual — please verify whether this is "
        f"expected (e.g. large RSS ingest) or a regression."
    )
    try:
        await _alert(
            f"[PodcastRAG] DB backup size anomaly {today.isoformat()}",
            body,
        )
    except Exception:  # noqa: BLE001
        logger.exception("db_backup: size anomaly alert dispatch failed")


async def _alert(subject: str, body: str) -> None:
    """ZSend admin alert. No-op when ZSend isn't configured."""
    if not settings.zsend_api_key or not settings.zsend_admin_to_email:
        logger.info("db_backup: ZSend not configured — alert skipped (%s)", subject)
        return
    recipients = [
        s.strip() for s in settings.zsend_admin_to_email.split(",") if s.strip()
    ]
    for to in recipients:
        try:
            await send_email(to, subject, body)
        except ZSendError as exc:
            if exc.retryable:
                raise
            logger.warning("db_backup: non-retryable ZSend error for %s: %s", to, exc)


def _libpq_url(url: str) -> str:
    """Strip the asyncpg driver suffix so pg_dump can parse the URL."""
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


class _ByteCountingReader:
    """Wraps a binary file-like to count bytes streamed through it."""

    def __init__(self, fileobj):
        self._fileobj = fileobj
        self.bytes_read = 0

    def read(self, size=-1):
        chunk = self._fileobj.read(size)
        if chunk:
            self.bytes_read += len(chunk)
        return chunk
