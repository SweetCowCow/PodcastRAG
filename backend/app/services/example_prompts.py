"""Per-show per-mode guiding example-prompt generation.

Part of change `per-show-mode-example-prompts`. Pre-generates 2–3 guiding
example questions per show, separately for each query mode (index / semantic /
chat), using the show's existing materials (episode ai_summary, deduped guests,
show title/description) as LLM input. Results persist to `show_example_prompts`
and are served by the public GET /shows/{id}/example-prompts endpoint as a
cold-start fallback for the trending-queries chip row.

Design D2/D6. Generation is idempotent per show+mode (a mode's prompts are
replaced only when fresh ones are produced) and fail-open (insufficient
materials or an LLM error skips persistence without raising into any caller —
notably the ingest chain).
"""
from __future__ import annotations

import logging
import re

from openai import AsyncOpenAI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.show import Show
from app.models.show_example_prompt import ExamplePromptMode, ShowExamplePrompt
from app.services.ai_step_resolver import get_step_config

logger = logging.getLogger(__name__)

# Material budget — keep the prompt token cost bounded.
_MAX_SUMMARIES = 12
_SUMMARY_CHAR_CAP = 6000
_MAX_GUESTS = 30
_MAX_QUESTIONS_PER_MODE = 3
_MAX_QUESTION_LEN = 60

# Per-mode generation instruction (design D6). Each asks for 2–3 questions in
# the style that mode is good at, in Traditional Chinese, one per line.
_MODE_INSTRUCTION: dict[ExamplePromptMode, str] = {
    ExamplePromptMode.index: (
        "請產生 2–3 個「索引模式」的引導範例。索引模式是精準關鍵字比對，"
        "範例必須是具體的名詞／人名／地名／作品名等實體關鍵字（1–6 個字），"
        "不要寫成完整問句。例如：「馬世芳」「開工歌單」。"
    ),
    ExamplePromptMode.semantic: (
        "請產生 2–3 個「語意模式」的引導範例。語意模式用意思相近找段落，"
        "範例應該是一句口語的描述句或問句，不需要精確用詞。"
        "例如：「他們怎麼看獨立樂團的困境」。"
    ),
    ExamplePromptMode.chat: (
        "請產生 2–3 個「對話模式」的引導範例。對話模式請 AI 跨集統整回答，"
        "範例應該是需要整理／比較／跨多集綜合的問題。"
        "例如：「整理這個節目對做音樂這件事的觀點」。"
    ),
}


async def gather_materials(db: AsyncSession, show_id) -> dict:
    """Collect a show's LLM input materials.

    Returns a dict with `show_title`, `show_description`, `summaries` (sampled
    + char-capped episode ai_summaries), `guests` (deduped across episodes), and
    `has_materials` (True iff there is at least one summary or guest). An unknown
    show, or one with neither summaries nor guests, yields `has_materials=False`.
    """
    show = await db.get(Show, show_id)
    if show is None:
        return {"has_materials": False}

    summary_rows = (
        await db.execute(
            select(Episode.ai_summary)
            .where(Episode.show_id == show_id)
            .where(Episode.ai_summary.isnot(None))
            .order_by(Episode.created_at.desc())
        )
    ).scalars().all()
    summaries: list[str] = []
    total = 0
    for s in summary_rows:
        text = (s or "").strip()
        if not text:
            continue
        if total + len(text) > _SUMMARY_CHAR_CAP:
            break
        summaries.append(text)
        total += len(text)
        if len(summaries) >= _MAX_SUMMARIES:
            break

    guest_rows = (
        await db.execute(select(Episode.guests).where(Episode.show_id == show_id))
    ).scalars().all()
    seen: set[str] = set()
    guests: list[str] = []
    for arr in guest_rows:
        for name in arr or []:
            n = (name or "").strip()
            if n and n not in seen:
                seen.add(n)
                guests.append(n)
            if len(guests) >= _MAX_GUESTS:
                break

    return {
        "show_title": show.title,
        "show_description": (show.description or "").strip(),
        "summaries": summaries,
        "guests": guests,
        "has_materials": bool(summaries or guests),
    }


def _build_prompt(mode: ExamplePromptMode, materials: dict) -> str:
    parts = [
        f"以下是 Podcast 節目《{materials.get('show_title', '')}》的內容素材，"
        "請依素材為這個節目產生引導使用者的範例查詢。",
    ]
    desc = materials.get("show_description")
    if desc:
        parts.append(f"節目簡介：{desc[:500]}")
    guests = materials.get("guests") or []
    if guests:
        parts.append("曾出現的來賓／人物：" + "、".join(guests[:20]))
    summaries = materials.get("summaries") or []
    if summaries:
        joined = "\n".join(f"- {s}" for s in summaries[:_MAX_SUMMARIES])
        parts.append("部分集數摘要：\n" + joined)
    parts.append(_MODE_INSTRUCTION[mode])
    parts.append(
        "只輸出範例本身，一行一個，不要加編號、引號、解說或其他文字。"
    )
    return "\n\n".join(parts)


def _parse_questions(text: str) -> list[str]:
    """Parse LLM output into a clean question list.

    Strips markdown code fences, leading list markers / numbering / quotes, and
    drops empty or over-long lines. Robust to AI Hub wrapping output in ```.
    """
    if not text:
        return []
    cleaned = re.sub(r"```[a-zA-Z]*", "", text).replace("```", "")
    out: list[str] = []
    for raw in cleaned.splitlines():
        line = raw.strip()
        # strip leading bullets / numbering: "1.", "1)", "-", "*", "・", "•"
        line = re.sub(r"^\s*(?:\d+[.)、]|[-*・•])\s*", "", line)
        line = line.strip().strip("「」\"'`").strip()
        if not line or len(line) > _MAX_QUESTION_LEN:
            continue
        out.append(line)
    # de-dupe preserving order
    seen: set[str] = set()
    deduped = []
    for q in out:
        if q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped


async def _call_chat(client: AsyncOpenAI, *, model: str, prompt: str) -> str:
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return (resp.choices[0].message.content or "").strip()


async def generate_for_show(db: AsyncSession, show_id) -> dict:
    """Generate + persist per-mode example prompts for one show.

    Returns a per-mode count dict, e.g. {"index": 3, "semantic": 2, "chat": 3}.
    Fail-open: insufficient materials or a config/LLM error skips persistence
    for the affected scope and returns zero counts there without raising. A mode
    whose generation yields no questions leaves that mode's existing rows intact
    (does not wipe prior prompts on a transient failure).
    """
    counts = {m.value: 0 for m in ExamplePromptMode}

    materials = await gather_materials(db, show_id)
    if not materials.get("has_materials"):
        logger.info("example_prompts: show %s has no materials — skip", show_id)
        return counts

    try:
        cfg = await get_step_config(db, "summary")
    except Exception:
        logger.warning(
            "example_prompts: summary step not configured — skip show %s", show_id,
            exc_info=True,
        )
        return counts

    client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key)

    for mode in ExamplePromptMode:
        try:
            text = await _call_chat(
                client, model=cfg.model, prompt=_build_prompt(mode, materials)
            )
            questions = _parse_questions(text)[:_MAX_QUESTIONS_PER_MODE]
        except Exception:
            logger.warning(
                "example_prompts: LLM failed for show %s mode %s — leave existing",
                show_id, mode.value, exc_info=True,
            )
            continue
        if not questions:
            continue
        # idempotent replace: clear this show+mode then re-insert in order.
        await db.execute(
            delete(ShowExamplePrompt).where(
                ShowExamplePrompt.show_id == show_id,
                ShowExamplePrompt.mode == mode,
            )
        )
        for i, q in enumerate(questions):
            db.add(
                ShowExamplePrompt(
                    show_id=show_id,
                    mode=mode,
                    question=q,
                    ordinal=i,
                    model=cfg.model,
                )
            )
        counts[mode.value] = len(questions)

    await db.commit()
    return counts
