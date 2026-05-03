"""Episode AI summary pipeline — map-reduce over transcript segments.

Stage 1 (map): chunk segments by token budget, ask LLM for 3-5 bullet
points per chunk.
Stage 2 (reduce): concatenate bullets, ask LLM for 80-150 chars Traditional
Chinese summary. Re-try once if length falls outside [50, 300].

Pure async functions — Celery task wraps it. tiktoken cl100k_base is used
for chunking; OpenAI-compatible chat.completions.create for both stages.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

import tiktoken
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

CHUNK_TOKEN_LIMIT = 12_000
MIN_SUMMARY_CHARS = 50
MAX_SUMMARY_CHARS = 300
TARGET_LOWER_CHARS = 80
TARGET_UPPER_CHARS = 150

_ENCODER = None


def _encoder() -> tiktoken.Encoding:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return _ENCODER


@dataclass(frozen=True)
class SegmentInput:
    """Lightweight DTO so callers can pass either ORM rows or test fixtures."""

    text: str
    start_time: float


def chunk_segments(
    segments: Sequence[SegmentInput],
    *,
    token_limit: int = CHUNK_TOKEN_LIMIT,
) -> list[str]:
    """Group segments into chunks not exceeding token_limit, segment-aligned.

    The last chunk is always preserved regardless of size — never merged.
    """
    enc = _encoder()
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for seg in segments:
        seg_text = seg.text.strip()
        if not seg_text:
            continue
        seg_tokens = len(enc.encode(seg_text))
        if current and current_tokens + seg_tokens > token_limit:
            chunks.append("\n".join(current))
            current = [seg_text]
            current_tokens = seg_tokens
        else:
            current.append(seg_text)
            current_tokens += seg_tokens
    if current:
        chunks.append("\n".join(current))
    return chunks


_MAP_PROMPT = """\
以下是一集 podcast 的部分逐字稿（純文字）。請列出這段內容的 3-5 條重點，
純條列、繁體中文、不必加標題、每條 1-2 句話。

=== 逐字稿開始 ===
{chunk_text}
=== 逐字稿結束 ===
"""

_REDUCE_PROMPT = """\
以下是一集 podcast 各段落的重點列表（已按時間順序）。請以 80-150 字之間
的繁體中文寫出整集摘要，使用流暢的敘述語氣（不必使用條列），不必開頭寫
「本集」或「這集」之類的固定句型，直接寫內容。

=== 重點列表開始 ===
{points_text}
=== 重點列表結束 ===
"""


async def _call_chat(
    client: AsyncOpenAI, *, model: str, prompt: str
) -> str:
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    content = resp.choices[0].message.content or ""
    return content.strip()


async def run_summary(
    segments: Iterable[SegmentInput],
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> str:
    """End-to-end: chunk → map → reduce → length-validate.

    Returns the final summary string. Caller must persist it.
    Raises whatever the OpenAI client raises on non-retryable errors.
    """
    seg_list = list(segments)
    if not seg_list:
        raise ValueError("run_summary called with no segments")

    chunks = chunk_segments(seg_list)
    logger.info("summary chunking: %d segments → %d chunks", len(seg_list), len(chunks))

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    # Stage 1: map.
    bullets_per_chunk: list[str] = []
    for idx, chunk in enumerate(chunks):
        prompt = _MAP_PROMPT.format(chunk_text=chunk)
        bullets = await _call_chat(client, model=model, prompt=prompt)
        bullets_per_chunk.append(bullets)
        logger.debug("summary map stage chunk %d/%d done", idx + 1, len(chunks))

    points_text = "\n\n".join(bullets_per_chunk)

    # Stage 2: reduce, with one retry on out-of-range length.
    summary = await _call_chat(
        client, model=model, prompt=_REDUCE_PROMPT.format(points_text=points_text)
    )
    if not (MIN_SUMMARY_CHARS <= len(summary) <= MAX_SUMMARY_CHARS):
        logger.warning(
            "summary out of range len=%d, retrying once", len(summary)
        )
        summary = await _call_chat(
            client,
            model=model,
            prompt=_REDUCE_PROMPT.format(points_text=points_text),
        )

    return summary
