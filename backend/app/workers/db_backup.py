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
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

import httpx
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.services.r2_backup_client import (
    _EXPECTED_RULE_IDS,
    abort_stale_multipart_uploads,
    apply_lifecycle_policy,
    bucket_usage,
    get_r2_backup_client,
    parse_recipients,
    read_verify_state,
    sweep_retention,
    verify_lifecycle_policy,
    write_verify_state,
)
from app.services.zsend import ZSendError, send_email
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

SIZE_RATIO_LOW = 0.5
SIZE_RATIO_HIGH = 2.0
STDERR_TRUNCATE_CHARS = 2000

# Absolute usage guard. The pre-existing day-over-day size ratio check is blind
# to accumulation: keeping one extra 7 GB copy per day is a sub-1% daily
# increase, which is how 108 objects / 472 GB built up unnoticed over 107 days.
MAX_EXPECTED_OBJECTS = 30
# Steady state is 23 artifacts x ~7.07 GB ~= 163 GB. 300 GB leaves headroom for
# dump growth (it grew 47% in three months) without going numb to a real fault:
# 300 GB is ~42 artifacts, far below the 108 this change was written for.
MAX_EXPECTED_BYTES = 300 * 1024**3


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

    await _apply_and_verify_lifecycle(client, bucket)

    started = time.monotonic()
    try:
        size_bytes = _stream_backup_to_r2(client, bucket, today_key, public_keys)
    except BaseException as exc:  # noqa: BLE001 — surface every failure
        # The streaming pipeline may have already uploaded a partial / empty
        # artifact (e.g. pg_dump failed AFTER age wrote its 200-byte header
        # and the upload completed). Delete it so we don't leave a corrupt
        # file shadowing yesterday's healthy backup.
        try:
            client.delete_object(Bucket=bucket, Key=today_key)
            logger.info("db_backup: deleted partial artifact %s", today_key)
        except Exception:  # noqa: BLE001
            logger.exception("db_backup: failed to delete partial artifact")

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

    promotion_ok = await _promote(client, bucket, today, today_key)

    # Size-anomaly check vs yesterday's daily artifact.
    await _check_size_anomaly(client, bucket, today, size_bytes)

    swept, aborted_uploads = await _sweep_and_abort(client, bucket, today)
    object_count, total_bytes = await _check_bucket_usage(client, bucket)

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
        "swept": swept,
        "aborted_uploads": aborted_uploads,
        "object_count": object_count,
        "total_bytes": total_bytes,
        "promotion_ok": promotion_ok,
    }


async def _apply_and_verify_lifecycle(client, bucket: str) -> None:
    """Apply the lifecycle policy, read it back, alert only on state change.

    The R2 token is known to lack bucket-configuration permission, so this
    verification currently fails every single day. Alerting on every failure
    would mean a daily email nobody can action — which is precisely the
    alert-fatigue that let the original defect survive. So the outcome is
    persisted and only transitions (ok -> failed, failed -> ok) are mailed.
    """
    outcome = "ok"
    detail = ""
    try:
        apply_lifecycle_policy(client, bucket)
        matched, actual = verify_lifecycle_policy(client, bucket)
        if not matched:
            outcome = "failed"
            detail = (
                f"Expected rule IDs: {sorted(_EXPECTED_RULE_IDS)}\n"
                f"Actual rule IDs:   {sorted(actual)}"
            )
    except (BotoCoreError, ClientError) as exc:
        outcome = "failed"
        code = ""
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
        detail = f"{type(exc).__name__}{f' ({code})' if code else ''}: {exc}"
        logger.warning("db_backup: lifecycle apply/verify failed: %s", detail)

    try:
        previous = read_verify_state(client, bucket)
    except Exception:  # noqa: BLE001 — state read must never break the backup
        logger.exception("db_backup: could not read lifecycle verify state")
        previous = None

    if outcome == previous:
        logger.warning(
            "db_backup: lifecycle verification still '%s' — alert suppressed", outcome
        )
        return

    if outcome == "ok" and previous is None:
        # First ever run, and everything is fine. "It works" is not news.
        logger.info("db_backup: lifecycle verification ok (first recorded run)")
        try:
            write_verify_state(client, bucket, outcome)
        except Exception:  # noqa: BLE001
            logger.exception("db_backup: could not persist lifecycle verify state")
        return

    if outcome == "ok":
        subject = "[PodcastRAG] DB backup lifecycle policy restored"
        body = (
            "The R2 bucket lifecycle policy now verifies successfully.\n\n"
            f"All expected rules are present: {sorted(_EXPECTED_RULE_IDS)}"
        )
    else:
        subject = "[PodcastRAG] DB backup lifecycle policy NOT applied"
        body = (
            "The R2 bucket lifecycle policy could not be applied or verified.\n\n"
            f"{detail}\n\n"
            "Retention is being enforced by the application-side sweep instead. "
            "To restore the lifecycle layer, upgrade the R2 API token from "
            "Object Read & Write to Admin Read & Write."
        )

    try:
        await _alert(subject, body)
    except Exception:  # noqa: BLE001
        logger.exception("db_backup: lifecycle alert dispatch failed")

    try:
        write_verify_state(client, bucket, outcome)
    except Exception:  # noqa: BLE001
        logger.exception("db_backup: could not persist lifecycle verify state")


async def _promote(client, bucket: str, today, today_key: str) -> bool:
    """Copy the day's artifact into weekly/ and monthly/ when due.

    Uses the managed `client.copy()` rather than `copy_object`: the dump is
    7.07 GB and `CopyObject` caps at 5 GiB per request, which is why weekly/
    stalled in May and monthly/ never had a single object. Failure here is
    alert-only — the daily artifact is already safely uploaded, and raising
    would trigger a Celery retry that re-runs the whole pg_dump.
    """
    now = datetime.now(timezone.utc)
    targets: list[tuple[str, str]] = []
    if now.weekday() == 6:  # Sunday
        targets.append(("weekly", f"weekly/{today.isoformat()}.dump.age"))
    if now.day == 1:
        targets.append(("monthly", f"monthly/{today.isoformat()}.dump.age"))

    ok = True
    for tier, dest_key in targets:
        try:
            client.copy({"Bucket": bucket, "Key": today_key}, bucket, dest_key)
            logger.info("db_backup: promoted to %s key=%s", tier, dest_key)
        except (BotoCoreError, ClientError) as exc:
            ok = False
            logger.exception("db_backup: %s promotion failed", tier)
            try:
                await _alert(
                    f"[PodcastRAG] DB backup promotion failed {today.isoformat()}",
                    f"Promotion of {today_key} to {dest_key} failed.\n\n"
                    f"Error: {type(exc).__name__}: {str(exc)[:STDERR_TRUNCATE_CHARS]}\n\n"
                    f"The daily artifact itself uploaded successfully — RPO is unaffected.",
                )
            except Exception:  # noqa: BLE001
                logger.exception("db_backup: promotion alert dispatch failed")
    return ok


async def _sweep_and_abort(client, bucket: str, today) -> tuple[dict | None, int | None]:
    """Enforce retention in application code, then clear stale multipart uploads.

    Returns (sweep result, aborted upload count); either is None if that step
    failed. Never raises — the day's backup is already uploaded.
    """
    subject = f"[PodcastRAG] DB backup retention sweep failed {today.isoformat()}"
    swept: dict | None = None
    aborted: int | None = None

    try:
        swept = sweep_retention(client, bucket)
    except (BotoCoreError, ClientError) as exc:
        logger.exception("db_backup: retention sweep failed")
        await _safe_alert(
            subject,
            f"The retention sweep raised before completing.\n\n"
            f"Error: {type(exc).__name__}: {str(exc)[:STDERR_TRUNCATE_CHARS]}",
        )
        return None, None

    if swept.get("needs_review"):
        pending = swept.get("pending_keys", [])
        await _safe_alert(
            "[PodcastRAG] DB backup retention sweep needs review",
            f"The sweep wanted to delete {len(pending)} objects, which exceeds the "
            f"safety limit. Nothing was deleted.\n\n"
            f"Keys that would have been deleted:\n" + "\n".join(pending),
        )
    elif swept.get("errors"):
        errors = swept["errors"]
        lines = [
            f"  {e.get('Key')}: {e.get('Code')} {e.get('Message')}" for e in errors
        ]
        await _safe_alert(
            subject,
            f"delete_objects reported {len(errors)} per-key failure(s) without "
            f"raising. Those objects are still in the bucket.\n\n" + "\n".join(lines),
        )

    try:
        aborted = abort_stale_multipart_uploads(client, bucket)
    except (BotoCoreError, ClientError) as exc:
        logger.exception("db_backup: stale multipart cleanup failed")
        await _safe_alert(
            subject,
            f"Aborting stale multipart uploads failed.\n\n"
            f"Error: {type(exc).__name__}: {str(exc)[:STDERR_TRUNCATE_CHARS]}",
        )

    return swept, aborted


async def _check_bucket_usage(client, bucket: str) -> tuple[int | None, int | None]:
    """Advisory absolute-usage guard. Never raises, never fails the backup."""
    try:
        usage = bucket_usage(client, bucket)
    except Exception:  # noqa: BLE001 — advisory only
        logger.exception("db_backup: bucket usage check failed (advisory)")
        return None, None

    count = usage["object_count"]
    total = usage["total_bytes"]
    logger.info(
        "db_backup: bucket usage objects=%d total_bytes=%d (%.2f GB)",
        count,
        total,
        total / 1024**3,
    )

    if count <= MAX_EXPECTED_OBJECTS and total <= MAX_EXPECTED_BYTES:
        return count, total

    per_prefix = "\n".join(
        f"  {p}: {s['count']} objects, {s['bytes'] / 1024**3:.2f} GB"
        for p, s in usage["prefixes"].items()
    )
    await _safe_alert(
        "[PodcastRAG] DB backup bucket usage alert",
        f"Backup bucket usage is above the expected bounds — retention may not "
        f"be working.\n\n"
        f"Objects: {count} (expected at most {MAX_EXPECTED_OBJECTS})\n"
        f"Total:   {total / 1024**3:.2f} GB (expected at most "
        f"{MAX_EXPECTED_BYTES / 1024**3:.0f} GB)\n\n"
        f"Per prefix:\n{per_prefix}",
    )
    return count, total


async def _safe_alert(subject: str, body: str) -> None:
    """_alert that never propagates a dispatch failure."""
    try:
        await _alert(subject, body)
    except Exception:  # noqa: BLE001
        logger.exception("db_backup: alert dispatch failed (%s)", subject)


def _stream_backup_to_r2(
    client, bucket: str, key: str, public_keys: list[str]
) -> int:
    """pg_dump | age --encrypt | upload_fileobj. Returns ciphertext byte count.

    No plaintext is ever written to disk — the dump bytes flow pg_dump.stdout
    → age.stdin → age.stdout → boto3 multipart upload buffer.

    Auth is passed via PGPASSWORD env (not the connection URL on argv) so the
    password does not leak into the worker container's `/proc/<pid>/cmdline`.
    """
    pg_args, pg_env = _pg_dump_argv_and_env(settings.database_url)

    age_cmd = ["age", "--encrypt"]
    for pk in public_keys:
        age_cmd.extend(["--recipient", pk])

    pg_dump = subprocess.Popen(
        pg_args,
        env=pg_env,
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


def _pg_dump_argv_and_env(database_url: str) -> tuple[list[str], dict[str, str]]:
    """Build pg_dump argv + env that keeps the password out of /proc/cmdline.

    pg_dump is invoked with split flags (-h / -p / -U / dbname) and the
    password is exported via PGPASSWORD in a fresh env, so any reader of
    `/proc/<pid>/cmdline` sees the host/user but never the secret.
    """
    parsed = urlparse(_libpq_url(database_url))
    host = parsed.hostname or "localhost"
    port = str(parsed.port) if parsed.port else "5432"
    user = unquote(parsed.username) if parsed.username else ""
    password = unquote(parsed.password) if parsed.password else ""
    dbname = parsed.path.lstrip("/") or "postgres"

    argv = [
        "pg_dump",
        "--format=custom",
        "--compress=9",
        "--no-acl",
        "--no-owner",
        "-h", host,
        "-p", port,
    ]
    if user:
        argv.extend(["-U", user])
    argv.append(dbname)

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password
    return argv, env


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
