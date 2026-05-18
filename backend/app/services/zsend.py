"""ZSend (Zeabur Email) HTTP client.

Used by the quota_digest beat task. When `settings.zsend_api_key` is unset,
callers should skip invoking these helpers; this module does not auto-skip
(callers are responsible for the no-op check) so that misconfiguration is
explicit at the call site.
"""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Per Zeabur Email (ZSend) docs the send endpoint lives at this URL.
ZSEND_BASE_URL = "https://api.zeabur.com"
ZSEND_SEND_PATH = "/api/v1/zsend/emails"

DEFAULT_TIMEOUT_SECONDS = 30.0


class ZSendError(Exception):
    """ZSend client error. ``retryable`` indicates whether the caller's
    retry policy (e.g. Celery autoretry_for) should treat this as transient.
    Network errors and 5xx are retryable; 4xx are not."""

    def __init__(self, message: str, *, retryable: bool, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


async def send_email(to: str, subject: str, body_text: str) -> None:
    """Send a plain-text email via ZSend. Raises ZSendError on failure.

    The caller MUST ensure ``settings.zsend_api_key`` and ``zsend_from_email``
    are configured. Validation is done here (raise if missing) so the failure
    mode is explicit, but production callers should pre-check to avoid the
    extra HTTP attempt.
    """
    if not settings.zsend_api_key:
        raise ZSendError("ZSEND_API_KEY is not configured", retryable=False)
    if not settings.zsend_from_email:
        raise ZSendError("ZSEND_FROM_EMAIL is not configured", retryable=False)

    payload = {
        "from": settings.zsend_from_email,
        "to": [to],  # ZSend expects an array of recipients
        "subject": subject,
        "text": body_text,
    }
    headers = {
        "Authorization": f"Bearer {settings.zsend_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{ZSEND_BASE_URL}{ZSEND_SEND_PATH}"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        # Network-level failures: connect refused, DNS, timeout. Retryable.
        raise ZSendError(
            f"ZSend request failed: {exc!r}", retryable=True
        ) from exc

    if 200 <= resp.status_code < 300:
        return

    # Non-2xx. Distinguish 4xx (client error, do not retry) from 5xx (retry).
    detail = resp.text[:500]
    retryable = resp.status_code >= 500
    logger.warning(
        "zsend send_email non-2xx: status=%s body=%s", resp.status_code, detail
    )
    raise ZSendError(
        f"ZSend HTTP {resp.status_code}: {detail}",
        retryable=retryable,
        status_code=resp.status_code,
    )


async def send_usage_threshold_alert(
    *,
    provider: str,
    severity: str,
    accumulated_usd: float,
    budget_usd: float,
    ratio: float,
    top_models: list[tuple[str, float]],
    taipei_date: str,
) -> None:
    """Send a multi-provider-usage-monitoring threshold alert email.

    Severity is "yellow" (>= 80%) or "red" (>= 95%). The email body is
    純文字繁中 so it renders cleanly in plain-text mail clients (no HTML
    template). Recipient list comes from ``ZSEND_ADMIN_TO_EMAIL``.

    Caller is responsible for ZSend pre-config check + dedupe (see
    ``app.workers.usage_alert``).
    """
    severity_label = "緊急" if severity == "red" else "提醒"
    ratio_pct = round(ratio * 100, 1)
    subject = (
        f"[PodcastRAG] {severity_label}：{provider} 用量已達 {ratio_pct}%"
        f"（${accumulated_usd:.2f} / ${budget_usd:.2f}）"
    )

    lines: list[str] = []
    lines.append(f"日期（台北）：{taipei_date}")
    lines.append(f"Provider：{provider}")
    lines.append(f"嚴重度：{severity}")
    lines.append(
        f"當月累積：${accumulated_usd:.2f} / 預算 ${budget_usd:.2f}"
        f"（{ratio_pct}%）"
    )
    lines.append("")
    if top_models:
        lines.append("本月花費前 3 名 model：")
        for i, (model, spend) in enumerate(top_models[:3], start=1):
            lines.append(f"  {i}. {model}: ${spend:.2f}")
        lines.append("")
    if severity == "red":
        lines.append(
            "已達 95%，請立即至 Zeabur AI Hub / OpenAI dashboard 充值，"
            "否則相關服務（轉錄 / 摘要 / 問答）可能中斷。"
        )
    else:
        lines.append("已達 80%，請留意是否需要充值。")
    lines.append("")
    lines.append("詳細圖表：admin 後台 → 服務用量")

    body = "\n".join(lines)
    recipients_raw = settings.zsend_admin_to_email or ""
    recipients = [s.strip() for s in recipients_raw.split(",") if s.strip()]
    for to in recipients:
        try:
            await send_email(to, subject, body)
        except ZSendError as exc:
            if exc.retryable:
                raise
            logger.warning(
                "usage_alert: non-retryable ZSend error for %s: %s", to, exc
            )


# ─────────────────────── task-failure-monitoring-and-circuit-breaker ───────

ADMIN_SERVICE_STATUS_URL = (
    "https://podcastrag.zeabur.app/admin/service-status"
)


def _taipei_iso(ts) -> str:
    """Format a UTC datetime as Asia/Taipei ISO-ish (純文字易讀)。"""
    if ts is None:
        return "—"
    from datetime import timezone, timedelta

    taipei = ts.astimezone(timezone(timedelta(hours=8)))
    return taipei.strftime("%Y-%m-%d %H:%M:%S (台北)")


def _zsend_recipients() -> list[str]:
    raw = settings.zsend_admin_to_email or ""
    return [s.strip() for s in raw.split(",") if s.strip()]


async def send_failure_alert(
    *,
    task_name: str,
    count: int,
    errors: list[str],
    taipei_ts: list[str],
    by_provider: dict[str, int] | None = None,
) -> None:
    """Sliding-window 失敗率告警信。失敗 ZSendError 直接 raise，
    caller (failure_alert worker) 用此訊號決定是否 mark alerted_at。
    """
    if not settings.zsend_api_key:
        raise ZSendError("ZSEND_API_KEY is not configured", retryable=False)

    subject = f"[PodcastRAG] task 失敗告警：{task_name}（{count} 次 / 30 分鐘）"
    lines = [
        f"task：{task_name}",
        f"30 分鐘內失敗次數：{count}",
        "",
    ]
    if by_provider:
        lines.append("按 provider 分組：")
        for pid, n in by_provider.items():
            lines.append(f"  • {pid or '（無）'}：{n}")
        lines.append("")
    lines.append("最近錯誤訊息（截斷至 200 字）：")
    for i, (err, ts) in enumerate(zip(errors[:3], taipei_ts[:3]), start=1):
        lines.append(f"  {i}. [{ts}] {err[:200]}")
    lines.append("")
    lines.append(f"後台：{ADMIN_SERVICE_STATUS_URL}")
    body = "\n".join(lines)

    for to in _zsend_recipients():
        await send_email(to, subject, body)


async def send_circuit_opened_alert(
    *,
    provider_id: str,
    latest_error: str,
    failure_count: int,
) -> None:
    """Circuit breaker 開啟通知信。"""
    if not settings.zsend_api_key:
        raise ZSendError("ZSEND_API_KEY is not configured", retryable=False)

    from datetime import datetime, timezone

    now_taipei = _taipei_iso(datetime.now(timezone.utc))
    subject = f"[PodcastRAG] 服務暫停：{provider_id} circuit opened"
    lines = [
        f"Provider：{provider_id}",
        f"暫停時間（台北）：{now_taipei}",
        f"觸發原因：過去 5 分鐘累計 {failure_count} 次永久錯誤",
        f"最近錯誤：{latest_error}",
        "",
        "預期行為：",
        f"  • 所有使用 {provider_id} 的 task 會自動暫停（自我 retry 5 分鐘後再試）",
        "  • 每 30 分鐘自動探測一次，若 provider 恢復會自動 close circuit + 寄恢復信",
        "  • 也可以到 admin 後台手動恢復",
        "",
        f"後台：{ADMIN_SERVICE_STATUS_URL}",
    ]
    body = "\n".join(lines)
    for to in _zsend_recipients():
        await send_email(to, subject, body)


async def send_recovery_notice(
    *,
    provider_id: str,
    opened_at,
    closed_at,
    paused_count: int,
    kind: str = "probe",
) -> None:
    """Circuit breaker 恢復通知信。``kind`` 為 probe / manual。"""
    if not settings.zsend_api_key:
        raise ZSendError("ZSEND_API_KEY is not configured", retryable=False)

    downtime_str = "—"
    if opened_at and closed_at:
        delta = closed_at - opened_at
        mins = int(delta.total_seconds() // 60)
        downtime_str = f"{mins} 分鐘"

    kind_label = "自動探測" if kind == "probe" else "管理員手動"
    subject = f"[PodcastRAG] 服務恢復：{provider_id} circuit closed（{kind_label}）"
    lines = [
        f"Provider：{provider_id}",
        f"暫停起時（台北）：{_taipei_iso(opened_at)}",
        f"恢復時間（台北）：{_taipei_iso(closed_at)}",
        f"暫停總時長：{downtime_str}",
        f"暫停期間累計影響 task：{paused_count} 個（會在下次 retry 時自動執行）",
        f"恢復方式：{kind_label}",
        "",
        f"後台：{ADMIN_SERVICE_STATUS_URL}",
    ]
    body = "\n".join(lines)
    for to in _zsend_recipients():
        await send_email(to, subject, body)
