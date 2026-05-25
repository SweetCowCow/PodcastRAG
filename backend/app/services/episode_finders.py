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
from typing import Any

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
SELECT e.id, e.title, e.published_at, e.guests, e.ai_summary
FROM episodes e
WHERE e.show_id = :show_id
  AND (
    (e.title_tsvector IS NOT NULL
     AND e.title_tsvector @@ to_tsquery('simple', :tsquery_text))
    OR EXISTS (
      SELECT 1 FROM episode_description_chunks d
      WHERE d.episode_id = e.id
        AND d.text_tsvector IS NOT NULL
        AND d.text_tsvector @@ to_tsquery('simple', :tsquery_text)
    )
  )
ORDER BY e.published_at DESC NULLS LAST
"""


async def find_episodes_by_topic(
    db: AsyncSession,
    show_id: uuid.UUID,
    topic_terms: list[str],
) -> list[EpisodeRef]:
    """Episodes whose `episodes.title_tsvector` OR any of its
    `episode_description_chunks.text_tsvector` rows match ANY of
    `topic_terms` (terms OR-joined into the tsquery).

    Hits `episodes.title_tsvector` + `episode_description_chunks`, but
    NOT `transcript_chunks` — both pools are metadata / summary-dense;
    transcript chunks would over-match on every passing mention of a
    generic word. Title was added by `enumeration-topic-finder-include-title`
    to recover episodes whose topic appears only in the title (e.g. the
    six 「歌單」 episodes from the 2026-05-17 q25 audit).

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

    # enumeration-rule-pattern-broaden bugfix: the LLM entity extractor
    # often returns multi-character phrases like "高雄美食" that Postgres'
    # `simple` analyzer keeps as a single token. But
    # `episode_description_chunks.text_tsvector` was built from a
    # jieba-tokenised stream (per `description_indexer.py` R3.1 design),
    # so the chunks store the individual lexemes "高雄" + "美食" — the
    # tsquery for the phrase as one token matches zero rows. We jieba-
    # tokenise each topic term here (filtering single-char and stopword
    # noise) so a phrase contributes its component words to the OR query.
    # Concrete impact (prod 2026-05-17): "高雄美食" went from 0 matches
    # to 37 matches against the same description corpus.
    expanded: list[str] = []
    seen: set[str] = set()
    for t in safe_terms:
        toks = [tk for tk in tokenizer.tokenize(t) if tk and tk.strip()]
        # Drop noise: single-char tokens (particles like 的、了、是) and
        # stopwords from TOPIC_STOPWORDS. If jieba produces nothing useful
        # for a term (e.g. all-stopword input), fall back to the original
        # term so we don't silently drop the LLM's signal.
        kept = [
            tk for tk in toks
            if len(tk) >= 2 and tk not in TOPIC_STOPWORDS
        ]
        if not kept:
            kept = [t]
        for tk in kept:
            if tk not in seen:
                seen.add(tk)
                expanded.append(tk)

    tsquery_text = " | ".join(expanded)
    params = {
        "show_id": show_id,
        "tsquery_text": tsquery_text,
    }
    result = await db.execute(text(_TOPIC_SQL), params)
    return [_row_to_episode_ref(row) for row in result.mappings()]


_BY_REF_EP_NUMBER_SQL = """
SELECT id, title, published_at, guests, ai_summary
FROM episodes
WHERE show_id = :show_id
  AND title ~* (
    E'(^|[^0-9A-Za-z])(EP|第)\\s*' || :n || E'(集)?($|[^0-9])'
  )
ORDER BY published_at DESC NULLS LAST
LIMIT 1
"""

_BY_REF_TITLE_SQL = """
SELECT id, title, published_at, guests, ai_summary
FROM episodes
WHERE show_id = :show_id
  AND title ILIKE :pattern
ORDER BY published_at DESC NULLS LAST
LIMIT 1
"""


async def find_by_ref(
    db: AsyncSession,
    show_id: uuid.UUID,
    ref: str,
) -> EpisodeRef | None:
    """Best-effort episode lookup by user-supplied reference string.

    Recognises three patterns:
      1. `EPnnn` / `epnnn` → matches title containing `EP<n>` or `第<n>集`.
      2. `第\\d+集` → same as (1), normalised.
      3. Anything else → falls back to `title ILIKE %ref%`.

    Returns the most recent matching episode by `published_at`, or `None`
    if no match. Returns `None` for empty / whitespace-only `ref`.
    """
    import re

    ref_clean = (ref or "").strip()
    if not ref_clean:
        return None

    m = re.search(r"(?:EP|ep|第)\s*(\d+)\s*(?:集)?", ref_clean)
    if m:
        n = m.group(1)
        params = {
            "show_id": show_id,
            "n": n,
        }
        result = await db.execute(text(_BY_REF_EP_NUMBER_SQL), params)
        row = result.mappings().first()
        if row is not None:
            return _row_to_episode_ref(row)

    params = {"show_id": show_id, "pattern": f"%{ref_clean}%"}
    result = await db.execute(text(_BY_REF_TITLE_SQL), params)
    row = result.mappings().first()
    return _row_to_episode_ref(row) if row is not None else None


_DATE_SQL_TEMPLATE = """
SELECT id, title, published_at, guests, ai_summary
FROM episodes
WHERE show_id = :show_id
  AND published_at BETWEEN :start AND :end
ORDER BY published_at {order_dir} NULLS LAST
{limit_clause}
"""


async def find_episodes_by_date_range(
    db: AsyncSession,
    show_id: uuid.UUID,
    start: datetime,
    end: datetime,
    *,
    order: str = "newest",
    limit: int | None = None,
) -> list[EpisodeRef]:
    """Episodes whose `published_at` falls inclusively between `start`
    and `end`. Both endpoints SHOULD be tz-aware (the entity extractor
    spec stipulates UTC); naive datetimes are passed through as-is and
    rely on Postgres comparing them at the column's timezone.

    `order='newest'` (default) → DESC, `order='oldest'` → ASC.
    `limit=None` (default) → unbounded; positive int → LIMIT N.
    """
    if order not in ("newest", "oldest"):
        raise ValueError(f"order must be 'newest' or 'oldest', got {order!r}")
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be None or >= 1, got {limit!r}")

    order_dir = "DESC" if order == "newest" else "ASC"
    params: dict[str, Any] = {
        "show_id": show_id,
        "start": start,
        "end": end,
    }
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT :limit"
        params["limit"] = limit
    sql = _DATE_SQL_TEMPLATE.format(order_dir=order_dir, limit_clause=limit_clause)
    result = await db.execute(text(sql), params)
    return [_row_to_episode_ref(row) for row in result.mappings()]


_RECENCY_SQL_TEMPLATE = """
SELECT e.id, e.title, e.published_at, e.guests, e.ai_summary
FROM episodes e
WHERE e.show_id = :show_id
  {year_clause}
  {topic_clause}
ORDER BY e.published_at {order_dir} NULLS LAST
LIMIT :n
"""

_RECENCY_COUNT_SQL_TEMPLATE = """
SELECT COUNT(*) AS total
FROM episodes e
WHERE e.show_id = :show_id
  {year_clause}
  {topic_clause}
"""

_YEAR_CLAUSE = (
    "AND EXTRACT(YEAR FROM e.published_at AT TIME ZONE 'Asia/Taipei') "
    "BETWEEN :year_start AND :year_end"
)

_TOPIC_CLAUSE = """
AND (
  (e.title_tsvector IS NOT NULL
   AND e.title_tsvector @@ to_tsquery('simple', :tsquery_text))
  OR EXISTS (
    SELECT 1 FROM episode_description_chunks d
    WHERE d.episode_id = e.id
      AND d.text_tsvector IS NOT NULL
      AND d.text_tsvector @@ to_tsquery('simple', :tsquery_text)
  )
)
"""


def _build_topic_tsquery(topic: str) -> str | None:
    """Mirror find_episodes_by_topic's escape + jieba expansion path.
    Returns None when topic yields no usable lexemes."""
    import re as _re
    cleaned = (topic or "").strip()
    if not cleaned:
        return None
    safe = _re.sub(r"[&|!()<:>\\]", " ", cleaned).strip()
    if not safe:
        return None
    toks = [tk for tk in tokenizer.tokenize(safe) if tk and tk.strip()]
    kept = [tk for tk in toks if len(tk) >= 2 and tk not in TOPIC_STOPWORDS]
    if not kept:
        kept = [safe]
    seen: set[str] = set()
    expanded: list[str] = []
    for tk in kept:
        if tk not in seen:
            seen.add(tk)
            expanded.append(tk)
    return " | ".join(expanded) if expanded else None


async def find_episodes_by_recency(
    db: AsyncSession,
    show_id: uuid.UUID,
    *,
    n: int = 5,
    order: str = "newest",
    topic: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
) -> dict:
    """Episodes ordered by `published_at` with optional topic + year filters.

    Returns `{"episodes": list[EpisodeRef], "n_total_matched": int}` —
    `n_total_matched` is the row count that would have been returned
    without the LIMIT, useful for "list_episodes returned 5 of 8" UX.

    Year filter uses `EXTRACT(YEAR FROM published_at AT TIME ZONE
    'Asia/Taipei')` — Taiwan-local calendar year, inclusive both ends.
    Topic filter reuses the simple_cjk + jieba expansion path from
    `find_episodes_by_topic`.
    """
    if order not in ("newest", "oldest"):
        raise ValueError(f"order must be 'newest' or 'oldest', got {order!r}")
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n!r}")
    if (year_start is None) != (year_end is None):
        raise ValueError("year_start and year_end must both be set or both None")
    if year_start is not None and year_end is not None and year_start > year_end:
        raise ValueError("year_start must be <= year_end")

    order_dir = "DESC" if order == "newest" else "ASC"
    params: dict[str, Any] = {"show_id": show_id, "n": n}
    year_clause = ""
    if year_start is not None and year_end is not None:
        year_clause = _YEAR_CLAUSE
        params["year_start"] = year_start
        params["year_end"] = year_end
    topic_clause = ""
    if topic:
        tsquery_text = _build_topic_tsquery(topic)
        if tsquery_text:
            topic_clause = _TOPIC_CLAUSE
            params["tsquery_text"] = tsquery_text

    sql = _RECENCY_SQL_TEMPLATE.format(
        order_dir=order_dir,
        year_clause=year_clause,
        topic_clause=topic_clause,
    )
    result = await db.execute(text(sql), params)
    episodes = [_row_to_episode_ref(row) for row in result.mappings()]

    count_sql = _RECENCY_COUNT_SQL_TEMPLATE.format(
        year_clause=year_clause,
        topic_clause=topic_clause,
    )
    count_params = {k: v for k, v in params.items() if k != "n"}
    count_result = await db.execute(text(count_sql), count_params)
    total = int(count_result.scalar() or 0)

    return {"episodes": episodes, "n_total_matched": total}
