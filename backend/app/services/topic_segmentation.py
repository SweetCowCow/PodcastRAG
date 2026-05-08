"""Per-segment topic classification via LLM (gpt-4o-mini).

Universal label set (8) + per-show extension labels (read from
`shows.segment_categories` JSONB). Single-label per segment.

Public API:
- `UNIVERSAL_LABELS`: tuple of 8 strings
- `classify_episode(db, episode_id) -> dict[segment_id, label]`
- `build_classification_prompt(show, segments)` (test-exposed)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.show import Show
from app.models.transcript import Transcript
from app.models.transcript_segment import TranscriptSegment
from app.services.ai_step_resolver import get_step_config

logger = logging.getLogger(__name__)

UNIVERSAL_LABELS: tuple[str, ...] = (
    "intro",
    "outro",
    "sponsor",
    "topic_main",
    "anecdote",
    "guest_intro",
    "factual",
    "meta",
)

UNIVERSAL_LABEL_DESCRIPTIONS = {
    "intro": "片頭歡迎、節目名介紹、本集主題提示",
    "outro": "結尾感謝、下集預告",
    "sponsor": "業配、優惠碼、廠商合作",
    "topic_main": "主題核心討論段",
    "anecdote": "個人故事 / 插科打諢 / 題外話",
    "guest_intro": "來賓介紹、背景說明",
    "factual": "具體資訊（時間、地點、價錢、人名）",
    "meta": "節目本身的話（譬如「這是第 100 集」「我們之前講過」）",
}

SHORT_SEGMENT_THRESHOLD = 5.0  # seconds

# Per-call segment batch size. 60 caused output truncation on talky episodes —
# JSON unterminated at char ~31400 hitting gpt-4o-mini's 16K output cap.
# Halved to 30 + explicit max_completion_tokens=8000 for safety margin.
SEGMENTS_PER_BATCH = 30
CHAT_MAX_OUTPUT_TOKENS = 8000

CHAT_RETRY_ATTEMPTS = 5
CHAT_RETRY_INITIAL_DELAY_S = 2.0
CHAT_RETRY_MAX_DELAY_S = 60.0

_RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
    "retry-after",
)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError)):
        return True
    if isinstance(exc, APIStatusError) and 500 <= getattr(exc, "status_code", 0) <= 599:
        return True
    return False


def _call_chat_with_retry(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None = None,
    max_attempts: int = CHAT_RETRY_ATTEMPTS,
) -> Any:
    """Chat completion with exponential-backoff retry + rate-limit header logs.

    Retries on RateLimitError / APITimeoutError / APIConnectionError /
    5xx APIStatusError. Logs rate-limit headers (when the proxy/server
    sends them) at WARNING on retry, INFO on final success.
    """
    delay = CHAT_RETRY_INITIAL_DELAY_S
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            raw_resp = client.chat.completions.with_raw_response.create(
                model=model,
                messages=messages,
                response_format=response_format or {"type": "text"},
                max_completion_tokens=CHAT_MAX_OUTPUT_TOKENS,
            )
            headers = getattr(raw_resp, "headers", {}) or {}
            interesting = {
                h: headers.get(h) for h in _RATE_LIMIT_HEADERS if h in headers
            }
            if interesting:
                logger.info("chat completion rate-limit headers: %s", interesting)
            return raw_resp.parse()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_retryable(exc) or attempt >= max_attempts - 1:
                raise
            headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
            interesting = {
                h: headers.get(h) for h in _RATE_LIMIT_HEADERS if h in headers
            }
            logger.warning(
                "chat call attempt %d/%d failed (%s); backing off %.1fs; rate-limit-headers=%s",
                attempt + 1,
                max_attempts,
                type(exc).__name__,
                delay,
                interesting or "n/a",
            )
            time.sleep(delay)
            delay = min(delay * 2, CHAT_RETRY_MAX_DELAY_S)
    assert last_exc is not None
    raise last_exc


def build_classification_prompt(
    show: Show, segments: list[TranscriptSegment]
) -> tuple[str, list[dict[str, Any]]]:
    """Return (system_prompt, user_payload_list) for LLM classification.

    The user payload is a list of segment dicts (`id`, `start`, `end`, `text`),
    which the model gets serialised as JSON in the user message.
    """
    show_extensions: list[dict[str, str]] = list(show.segment_categories or [])

    lines = [
        "你是 podcast 段落分類器。對給定的每個 segment，從以下類別中**選一個最貼切的標籤**：",
        "",
        "[通用類別]",
    ]
    for label in UNIVERSAL_LABELS:
        lines.append(f"- {label}: {UNIVERSAL_LABEL_DESCRIPTIONS[label]}")

    if show_extensions:
        lines.append("")
        lines.append(f"[節目專屬類別 — {show.title}]")
        for ext in show_extensions:
            name = str(ext.get("name", "")).strip()
            desc = str(ext.get("desc", "")).strip()
            if name:
                lines.append(f"- {name}: {desc}")

    lines.extend([
        "",
        "規則：",
        "1. 每個 segment 只能選一個標籤",
        "2. 標籤名稱必須完全符合上面列出的類別（不可自創）",
        "3. 段落很短（< 5 秒、< 10 字）若難以判斷，跟前一段同 label",
        "",
        "輸出格式 JSON：",
        '{"labels": [{"id": "<segment_id>", "label": "<label>"}, ...]}',
    ])
    system_prompt = "\n".join(lines)

    user_payload = [
        {
            "id": str(s.id),
            "start": round(float(s.start_time), 2),
            "end": round(float(s.end_time), 2),
            "text": s.text or "",
        }
        for s in segments
    ]
    return system_prompt, user_payload


def _allowed_label_set(show: Show) -> set[str]:
    extensions = {
        str(ext.get("name", "")).strip()
        for ext in (show.segment_categories or [])
        if ext.get("name")
    }
    return set(UNIVERSAL_LABELS) | extensions


async def classify_episode_no_persist(
    db: AsyncSession,
    episode_id: uuid.UUID,
    *,
    client: OpenAI | None = None,
    model: str | None = None,
) -> dict[uuid.UUID, str]:
    """Same as classify_episode but does NOT write to DB.

    Used by A/B comparison runs where we want to evaluate a different model
    without overwriting prod labels.
    """
    return await _classify_episode_impl(
        db, episode_id, client=client, model=model, persist=False
    )


async def classify_episode(
    db: AsyncSession,
    episode_id: uuid.UUID,
    *,
    client: OpenAI | None = None,
    model: str | None = None,
) -> dict[uuid.UUID, str]:
    """Classify every segment of one episode via LLM. Returns id→label map.

    If `client` and `model` are provided, use them directly (bypass the
    `summary` step config). This lets backfill scripts route around the
    Zeabur AI Hub when it's throttling.
    """
    return await _classify_episode_impl(
        db, episode_id, client=client, model=model, persist=True
    )


async def _classify_episode_impl(
    db: AsyncSession,
    episode_id: uuid.UUID,
    *,
    client: OpenAI | None,
    model: str | None,
    persist: bool,
) -> dict[uuid.UUID, str]:
    episode = await db.get(Episode, episode_id)
    if episode is None:
        logger.warning("episode %s not found", episode_id)
        return {}

    show = await db.get(Show, episode.show_id)
    if show is None:
        logger.warning("show %s not found", episode.show_id)
        return {}

    transcript = (
        await db.execute(
            select(Transcript).where(Transcript.episode_id == episode_id)
        )
    ).scalar_one_or_none()
    if transcript is None:
        logger.warning("transcript for episode %s not found", episode_id)
        return {}

    segments = (
        await db.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == transcript.id)
            .order_by(TranscriptSegment.start_time)
        )
    ).scalars().all()
    if not segments:
        return {}

    if client is None or model is None:
        step_config = await get_step_config(db, "summary")
        client = OpenAI(base_url=step_config.base_url, api_key=step_config.api_key)
        model = step_config.model

    allowed = _allowed_label_set(show)
    label_map: dict[uuid.UUID, str] = {}

    # Process segments in batches to stay under model context length.
    # Long episodes (>2hr talky podcast) can have 1500+ segments / 200K+
    # input tokens — beyond gpt-4o-mini's 128K limit. Splitting per-batch
    # gives independent classification calls; the system_prompt is
    # re-sent each batch (a few-hundred token overhead per batch).
    for batch_start in range(0, len(segments), SEGMENTS_PER_BATCH):
        batch = segments[batch_start : batch_start + SEGMENTS_PER_BATCH]
        system_prompt, user_payload = build_classification_prompt(show, batch)

        # Run the sync OpenAI call in a thread so asyncio.gather over many
        # episodes actually parallelises (otherwise the sync HTTP block
        # serialises every call inside the event loop, defeating
        # `--concurrency` in the backfill script).
        resp = await asyncio.to_thread(
            _call_chat_with_retry,
            client,
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"segments": user_payload}, ensure_ascii=False
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except ValueError:
            logger.exception(
                "episode %s batch %d: LLM returned invalid JSON",
                episode_id,
                batch_start // SEGMENTS_PER_BATCH,
            )
            continue

        for item in data.get("labels", []):
            try:
                sid = uuid.UUID(str(item["id"]))
                label = str(item["label"]).strip()
            except (KeyError, ValueError):
                continue
            if label not in allowed:
                logger.warning(
                    "episode %s segment %s: unknown label %r → topic_main fallback",
                    episode_id,
                    sid,
                    label,
                )
                label = "topic_main"
            label_map[sid] = label

    # Short-segment fallback: < 5s segments without a label inherit the previous segment's label.
    prev_label = "topic_main"
    for s in segments:
        duration = float(s.end_time) - float(s.start_time)
        if s.id in label_map:
            prev_label = label_map[s.id]
        elif duration < SHORT_SEGMENT_THRESHOLD:
            label_map[s.id] = prev_label

    # Persist
    if persist:
        for sid, label in label_map.items():
            await db.execute(
                update(TranscriptSegment)
                .where(TranscriptSegment.id == sid)
                .values(topic_label=label)
            )
        await db.commit()

    return label_map
