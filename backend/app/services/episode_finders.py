"""Tool-like episode finder functions for cross-episode enumeration.

Three async finders + small helper that compose what the chat path needs
when the entity_extraction LLM step pulls guests / topics / date_range
out of the user's question. Each finder is intentionally narrow so the
function signature could later become a tool definition (OpenAI
function-calling, MCP tool, etc.) without re-shaping the SQL.

`_compute_enumeration_episodes` in `app/api/query.py` dispatches to these
finders and combines results (AND-with-fallback) — see design.md
Decision 4-5 in the `r3-3-chat-enum-grounding` change.
"""
from __future__ import annotations

import json as _stdlib_json
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.query import EpisodeRef
from app.services import tokenizer

# Hardcoded stopword set used to filter out generic tokens that the
# entity_extraction LLM (or our jieba fallback) sometimes lets through.
# These words match too broadly against episode descriptions — letting
# them reach the tsquery turns the enumeration list into noise.
# Starter set per design Decision 3; revisit if prod traffic shows
# leakage. Promote to admin-tunable storage if the list grows past ~50.
TOPIC_STOPWORDS: set[str] = {
    # 通用泛詞
    "節目", "集數", "集", "主持人", "他們", "我們", "你們",
    "什麼", "怎麼", "為什麼", "有沒有", "多少", "如何",
    # 平台泛詞
    "podcast", "Podcast", "PODCAST",
    # 指示詞
    "這集", "那集", "哪集", "哪幾集", "那幾集",
    # 連接詞
    "或", "及", "與", "的", "了",
}


def extract_topic_terms_from_question(question: str) -> list[str]:
    """Jieba-tokenise a question and return multi-char terms suitable for
    `to_tsquery('simple', :tsquery_text)`.

    Drops: empty tokens, length-1 tokens, tokens in `TOPIC_STOPWORDS`.
    Preserves order, de-duplicates while keeping first occurrence.

    Used when the user's question matched a rule pattern (`[哪那]幾集`)
    but the LLM extracted no `topics` — we recover topic intent from the
    question text itself rather than falling back to "list every episode".
    """
    if not question:
        return []
    tokens = tokenizer.tokenize(question)
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokens:
        t = (tok or "").strip()
        if len(t) < 2:
            continue
        if t in TOPIC_STOPWORDS:
            continue
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _row_to_episode_ref(row) -> EpisodeRef:
    return EpisodeRef(
        episode_id=row["id"],
        title=row["title"],
        published_at=row["published_at"],
        guests=list(row["guests"] or []),
        ai_summary=row["ai_summary"],
    )


_GUEST_SQL = """
SELECT id, title, published_at, guests, ai_summary
FROM episodes
WHERE show_id = :show_id
  AND guests @> CAST(:guests AS jsonb)
ORDER BY published_at DESC NULLS LAST
"""


async def find_episodes_by_guest(
    db: AsyncSession,
    show_id: uuid.UUID,
    guests: list[str],
) -> list[EpisodeRef]:
    """Episodes whose `guests` JSONB array contains ALL of `guests`.

    Empty `guests` list returns `[]` without hitting the DB — callers
    SHOULD short-circuit this case themselves to avoid noisy SQL traces,
    but the safety check here keeps the function tool-callable in a
    future agentic path that might invoke it with empty args.
    """
    if not guests:
        return []
    params = {
        "show_id": show_id,
        "guests": _stdlib_json.dumps(guests),
    }
    result = await db.execute(text(_GUEST_SQL), params)
    return [_row_to_episode_ref(row) for row in result.mappings()]


_TOPIC_SQL = """
SELECT DISTINCT ON (e.id)
       e.id, e.title, e.published_at, e.guests, e.ai_summary
FROM episodes e
JOIN episode_description_chunks d ON d.episode_id = e.id
WHERE e.show_id = :show_id
  AND d.text_tsvector IS NOT NULL
  AND d.text_tsvector @@ to_tsquery('simple', :tsquery_text)
ORDER BY e.id, e.published_at DESC NULLS LAST
"""


_TOPIC_SQL_OUTER_ORDER = """
SELECT * FROM (
""" + _TOPIC_SQL + """
) ranked
ORDER BY published_at DESC NULLS LAST
"""


async def find_episodes_by_topic(
    db: AsyncSession,
    show_id: uuid.UUID,
    topic_terms: list[str],
) -> list[EpisodeRef]:
    """Episodes whose `episode_description_chunks.text_tsvector` matches
    ANY of `topic_terms` (terms OR-joined into the tsquery).

    Hits `episode_description_chunks`, NOT `transcript_chunks` — see
    design.md Decision 2: description chunks are summary-dense, transcript
    chunks would over-match on every passing mention of a generic word.

    Empty `topic_terms` returns `[]` (same safety contract as the guest
    finder). Falsy / whitespace-only terms are dropped before the
    tsquery is built.
    """
    cleaned = [t.strip() for t in topic_terms if t and t.strip()]
    if not cleaned:
        return []
    # tsquery operators are escaped lightly: replace `&|!()<:>\\` with
    # space so a stray operator inside a LLM-extracted topic doesn't
    # blow up to_tsquery(). Mirrors `app.services.rag._build_ts_query`.
    import re as _re
    safe_terms: list[str] = []
    for t in cleaned:
        s = _re.sub(r"[&|!()<:>\\]", " ", t).strip()
        if s:
            safe_terms.append(s)
    if not safe_terms:
        return []
    tsquery_text = " | ".join(safe_terms)
    params = {
        "show_id": show_id,
        "tsquery_text": tsquery_text,
    }
    result = await db.execute(text(_TOPIC_SQL_OUTER_ORDER), params)
    return [_row_to_episode_ref(row) for row in result.mappings()]


_DATE_SQL = """
SELECT id, title, published_at, guests, ai_summary
FROM episodes
WHERE show_id = :show_id
  AND published_at BETWEEN :start AND :end
ORDER BY published_at DESC NULLS LAST
"""


async def find_episodes_by_date_range(
    db: AsyncSession,
    show_id: uuid.UUID,
    start: datetime,
    end: datetime,
) -> list[EpisodeRef]:
    """Episodes whose `published_at` falls inclusively between `start`
    and `end`. Both endpoints SHOULD be tz-aware (the entity extractor
    spec stipulates UTC); naive datetimes are passed through as-is and
    rely on Postgres comparing them at the column's timezone.
    """
    params = {
        "show_id": show_id,
        "start": start,
        "end": end,
    }
    result = await db.execute(text(_DATE_SQL), params)
    return [_row_to_episode_ref(row) for row in result.mappings()]
