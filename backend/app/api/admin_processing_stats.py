"""Admin endpoint: `/admin/processing-stats` — backfill progress overview.

Returns a single JSON object with three-dimensional progress (transcription /
summary / topic segmentation) and a 24-hour delta summary, intended for the
admin Queue Tab "Processing Overview" block (`backfill-progress-admin-tab`).

The frontend polls this endpoint every 30 s. Numbers are computed via SQL on
`episodes`, `transcripts`, `transcript_segments`. Failures within the last
24 hours come from the Celery result backend (`celery-task-meta-*` keys with
`status=FAILURE`); after the F2 change archives the `task_failure_log` table,
`_fetch_failures()` can be swapped to read from that table without changing
the response shape.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_admin
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptStatus
from app.models.transcript_segment import TranscriptSegment

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin-processing-stats"],
    dependencies=[Depends(require_admin)],
)

# Limit how many Celery result-backend keys we inspect per call. The result
# backend can hold tens of thousands of keys when batches misbehave; scanning
# every one on each 30-s poll would amplify the cost dramatically.
_MAX_CELERY_KEYS_SCANNED = 5000

# Sample error message truncation length for `last_24h.failures[*].sample_error`.
_SAMPLE_ERROR_MAX_LEN = 500

# Task name prefixes we report on. Anything else (cron_tick, db_backup, etc.)
# is uninteresting noise for processing-progress reporting.
_REPORTED_TASK_NAME_PREFIXES = (
    "app.workers.tasks.",
    "app.workers.topic_task.",
    "app.workers.summary_task.",
)


def _fetch_failures(now: datetime) -> list[dict[str, Any]]:
    """Return last-24h Celery FAILURE entries grouped by task_name.

    v1 implementation: scan the Celery result backend (`celery-task-meta-*`).
    After F2 archives `task_failure_log`, swap this for a SQL query against
    that table; the returned shape (list of `{task_name, count, sample_error}`)
    stays the same so the caller does not need to change.
    """
    # Lazy import — avoids loading Celery + Redis at module import time, which
    # matters for unit tests that monkeypatch this function.
    try:
        from app.workers.celery_app import celery_app
    except Exception:
        logger.exception("processing-stats: failed to import celery_app")
        return []

    try:
        backend = celery_app.backend
        # Most setups use the Redis result backend, which exposes `.client`.
        client = getattr(backend, "client", None)
        if client is None:
            logger.warning(
                "processing-stats: celery backend has no Redis client; "
                "skipping failure scan (backend=%r)",
                type(backend).__name__,
            )
            return []
    except Exception:
        logger.exception("processing-stats: failed to access celery backend")
        return []

    cutoff = now - timedelta(hours=24)
    grouped: dict[str, dict[str, Any]] = {}
    scanned = 0
    try:
        for raw_key in client.scan_iter(match="celery-task-meta-*", count=500):
            scanned += 1
            if scanned > _MAX_CELERY_KEYS_SCANNED:
                logger.warning(
                    "processing-stats: scanned %d celery-task-meta keys; "
                    "capping to avoid amplifying poll cost",
                    _MAX_CELERY_KEYS_SCANNED,
                )
                break
            try:
                raw = client.get(raw_key)
                if raw is None:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                meta = json.loads(raw)
            except Exception:
                continue
            if meta.get("status") != "FAILURE":
                continue
            task_name = meta.get("task") or meta.get("task_name") or ""
            if not task_name or not task_name.startswith(_REPORTED_TASK_NAME_PREFIXES):
                continue
            date_done_raw = meta.get("date_done")
            if not date_done_raw:
                continue
            try:
                # Celery serialises date_done as ISO 8601; treat naive strings
                # as UTC (matches Celery's default `enable_utc=True`).
                if isinstance(date_done_raw, str):
                    date_done = datetime.fromisoformat(
                        date_done_raw.replace("Z", "+00:00")
                    )
                else:
                    continue
                if date_done.tzinfo is None:
                    date_done = date_done.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if date_done < cutoff:
                continue
            result = meta.get("result") or {}
            if isinstance(result, dict):
                err_msg = (
                    result.get("exc_message")
                    or result.get("exc_type")
                    or result.get("message")
                    or ""
                )
                if isinstance(err_msg, list):
                    err_msg = " ".join(str(p) for p in err_msg)
            else:
                err_msg = str(result)
            err_msg = (err_msg or "")[:_SAMPLE_ERROR_MAX_LEN]
            entry = grouped.setdefault(
                task_name, {"task_name": task_name, "count": 0, "sample_error": ""}
            )
            entry["count"] += 1
            if not entry["sample_error"] and err_msg:
                entry["sample_error"] = err_msg
    except Exception:
        logger.exception("processing-stats: failure scan aborted partway")

    # Stable order: highest count first, then task_name for determinism.
    return sorted(
        grouped.values(), key=lambda e: (-e["count"], e["task_name"])
    )


@router.get("/processing-stats")
async def get_processing_stats(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return a single object describing backfill progress + last 24h activity."""
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    # ── transcription ──
    total_episodes = await db.scalar(select(func.count()).select_from(Episode)) or 0
    transcribed_episodes = (
        await db.scalar(
            select(func.count())
            .select_from(Transcript)
            .where(Transcript.status == TranscriptStatus.completed)
        )
        or 0
    )

    # ── summary ──
    # Denominator = transcribed episodes (you cannot summarise an episode
    # without a transcript). Numerator = episodes whose ai_summary_status is
    # `done`. This matches the operator's mental model: "out of transcribed
    # episodes, how many have a summary?".
    summary_total = transcribed_episodes
    summary_completed = (
        await db.scalar(
            select(func.count())
            .select_from(Episode)
            .join(Transcript, Transcript.episode_id == Episode.id)
            .where(
                Transcript.status == TranscriptStatus.completed,
                Episode.ai_summary_status == "done",
            )
        )
        or 0
    )

    # ── topic segmentation ──
    # Primary unit: SEGMENT counts. The 5/10 incident showed distinct-episode
    # counts are misleading (an episode counts as "done" once any segment is
    # labelled, hiding partial progress). We report both so the bar can show
    # segment ratio while the secondary text shows episode coverage.
    total_segments = (
        await db.scalar(select(func.count()).select_from(TranscriptSegment)) or 0
    )
    labelled_segments = (
        await db.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.topic_label.isnot(None))
        )
        or 0
    )
    # Episode coverage: an episode is "fully labelled" iff every one of its
    # segments has a non-null topic_label. Compute via "no NULL segments".
    topic_total_episodes = (
        await db.scalar(
            select(func.count(func.distinct(Transcript.episode_id)))
            .select_from(Transcript)
            .where(Transcript.status == TranscriptStatus.completed)
        )
        or 0
    )
    # Per-transcript subquery: count segments + count of NULL-label segments.
    # An episode is "fully labelled" iff seg_count > 0 AND null_count == 0.
    seg_counts_subq = (
        select(
            Transcript.episode_id.label("eid"),
            func.count(TranscriptSegment.id).label("seg_count"),
            func.sum(
                case((TranscriptSegment.topic_label.is_(None), 1), else_=0)
            ).label("null_count"),
        )
        .select_from(Transcript)
        .join(TranscriptSegment, TranscriptSegment.transcript_id == Transcript.id)
        .where(Transcript.status == TranscriptStatus.completed)
        .group_by(Transcript.episode_id)
        .subquery()
    )
    topic_completed_episodes = (
        await db.scalar(
            select(func.count())
            .select_from(seg_counts_subq)
            .where(
                seg_counts_subq.c.seg_count > 0,
                seg_counts_subq.c.null_count == 0,
            )
        )
        or 0
    )

    # ── last 24h deltas ──
    transcribed_episodes_24h = (
        await db.scalar(
            select(func.count())
            .select_from(Transcript)
            .where(
                Transcript.status == TranscriptStatus.completed,
                Transcript.transcribed_at.isnot(None),
                Transcript.transcribed_at >= cutoff_24h,
            )
        )
        or 0
    )
    # No timestamp on labelled segments (`transcript_segments.topic_label`
    # column has no `_at`). Approximation: count segments whose transcript
    # was updated within 24h AND segment has a label. This will over-count
    # when a transcript is re-touched for other reasons; flagged as v1
    # caveat — full per-segment timestamp tracking is F2 scope.
    labeled_segments_24h = (
        await db.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .join(Transcript, Transcript.id == TranscriptSegment.transcript_id)
            .where(
                TranscriptSegment.topic_label.isnot(None),
                Transcript.updated_at.isnot(None),
                Transcript.updated_at >= cutoff_24h,
            )
        )
        or 0
    )

    failures = _fetch_failures(now)

    def _ratio(num: int, den: int) -> float:
        if den <= 0:
            return 0.0
        return round(num / den, 4)

    return {
        "transcription": {
            "completed_episodes": int(transcribed_episodes),
            "total_episodes": int(total_episodes),
            "ratio": _ratio(transcribed_episodes, total_episodes),
        },
        "summary": {
            "completed_episodes": int(summary_completed),
            "total_episodes": int(summary_total),
            "ratio": _ratio(summary_completed, summary_total),
        },
        "topic_seg": {
            "completed_segments": int(labelled_segments),
            "total_segments": int(total_segments),
            "ratio": _ratio(labelled_segments, total_segments),
            "completed_episodes": int(topic_completed_episodes),
            "total_episodes_with_transcript": int(topic_total_episodes),
            "episode_ratio": _ratio(topic_completed_episodes, topic_total_episodes),
        },
        "last_24h": {
            "transcribed_episodes": int(transcribed_episodes_24h),
            "labeled_segments": int(labeled_segments_24h),
            "failures": failures,
        },
        "as_of": now.isoformat(),
    }
