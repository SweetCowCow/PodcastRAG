"""Beat-driven monthly reminder for stale RAG-eval baselines.

Looks at every show that has a golden-set dataset shipped in
`backend/eval/datasets/*.json` (`_`-prefixed files excluded). For each show,
finds the latest matching `backend/eval/results/eval-{slug}-*.json`. If the
latest run is older than `STALE_DAYS` days (or there is no run at all),
include the show in a digest email sent via ZSend to admins.

Schedule: 1st of each month, UTC 09:00 (台北 17:00).

ZSend not configured → no-op log line. ZSend transient errors → autoretry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.zsend import ZSendError, send_email
from app.workers.celery_app import celery_app
from app.workers.failure_hooks import (
    check_circuit_or_retry,
    record_task_failure_unless_logged,
)

logger = logging.getLogger(__name__)

# backend/app/workers/eval_reminder.py → backend/eval/{datasets,results}
_EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
DATASETS_DIR = _EVAL_DIR / "datasets"
RESULTS_DIR = _EVAL_DIR / "results"

STALE_DAYS = 30
_RESULT_RE = re.compile(r"^eval-(?P<slug>.+)-(?P<ts>\d{8}T\d{6}Z)\.json$")


def _list_shipped_datasets() -> list[dict]:
    """Return list of {slug, show_id} for each non-underscore dataset present."""
    if not DATASETS_DIR.exists():
        return []
    out: list[dict] = []
    for p in DATASETS_DIR.glob("*.json"):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        slug = data.get("show_slug")
        show_id = data.get("show_id")
        if slug and show_id:
            out.append({"slug": slug, "show_id": show_id})
    return out


def _latest_run_ts(slug: str) -> datetime | None:
    """Return timestamp of latest run for `slug`, or None if no runs exist."""
    if not RESULTS_DIR.exists():
        return None
    latest: datetime | None = None
    for p in RESULTS_DIR.glob(f"eval-{slug}-*.json"):
        m = _RESULT_RE.match(p.name)
        if not m or m.group("slug") != slug:
            continue
        try:
            ts = datetime.strptime(m.group("ts"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if latest is None or ts > latest:
            latest = ts
    return latest


def _stale_shows(now: datetime, stale_days: int = STALE_DAYS) -> list[dict]:
    """Return [{slug, show_id, last_run, days_stale}] for shows overdue for eval."""
    cutoff = now - timedelta(days=stale_days)
    out: list[dict] = []
    for ds in _list_shipped_datasets():
        latest = _latest_run_ts(ds["slug"])
        if latest is None:
            out.append({**ds, "last_run": None, "days_stale": None})
        elif latest < cutoff:
            out.append({
                **ds,
                "last_run": latest.isoformat(),
                "days_stale": (now - latest).days,
            })
    return out


def _compose_email(stale: list[dict]) -> tuple[str, str]:
    """Return (subject, plain_text_body)."""
    n = len(stale)
    subject = f"[PodcastRAG] {n} show(s) need a RAG-eval baseline refresh"
    lines = [
        f"以下 {n} 個 show 的 RAG-eval baseline 已超過 {STALE_DAYS} 天未跑（或從未跑過）：",
        "",
    ]
    for s in stale:
        if s["last_run"] is None:
            lines.append(f"  • {s['slug']} — never run")
        else:
            lines.append(f"  • {s['slug']} — last run {s['last_run']} ({s['days_stale']} days ago)")
    lines += [
        "",
        "要跑 baseline：",
        "    python -m backend.eval.runners.run \\",
        "        --dataset backend/eval/datasets/<slug>.json \\",
        "        --backend-url https://api.podcastrag.app \\",
        "        --auth-token \"$EVAL_AUTH_TOKEN\" --top-k 5",
        "",
        "（若新 show 還沒做 golden set，先用 rag-eval-runner skill 跑 Recipe 2。）",
    ]
    return subject, "\n".join(lines)


class _EvalReminderTask(celery_app.Task):
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # type: ignore[override]
        record_task_failure_unless_logged(
            task_name="app.workers.eval_reminder.send_eval_reminder",
            args=args,
            exc=exc,
            provider_id="zsend",
            retry_count=int(self.request.retries or 0),
        )


@celery_app.task(
    base=_EvalReminderTask,
    bind=True,
    name="app.workers.eval_reminder.send_eval_reminder",
    autoretry_for=(httpx.HTTPError, httpx.TimeoutException),
    max_retries=2,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
)
def send_eval_reminder(self) -> dict:
    # task-failure-monitoring-and-circuit-breaker task 5.1: zsend circuit
    check_circuit_or_retry(self, "zsend")
    return asyncio.run(_run())


async def _run() -> dict:
    if not settings.zsend_api_key or not settings.zsend_admin_to_email:
        logger.info("eval_reminder: ZSend not configured — skipping")
        return {"skipped": "zsend_unconfigured"}

    now = datetime.now(timezone.utc)
    stale = _stale_shows(now)
    if not stale:
        logger.info("eval_reminder: no stale shows")
        return {"sent_count": 0, "stale_count": 0}

    subject, body = _compose_email(stale)
    recipients = [
        e.strip() for e in str(settings.zsend_admin_to_email).split(",") if e.strip()
    ]

    sent = 0
    for to in recipients:
        try:
            await send_email(subject=subject, to=[to], text=body)
            sent += 1
        except ZSendError as exc:
            logger.warning("eval_reminder: zsend failed for %s: %s", to, exc)
    logger.info("eval_reminder: sent %d email(s) for %d stale show(s)", sent, len(stale))
    return {"sent_count": sent, "stale_count": len(stale)}
