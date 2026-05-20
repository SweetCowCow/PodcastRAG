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
  AND (
    title ILIKE :ep_token_lower OR title ILIKE :ep_token_upper
    OR title ILIKE :chinese_ep_token
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
            "ep_token_lower": f"%ep{n}%",
            "ep_token_upper": f"%EP{n}%",
            "chinese_ep_token": f"%第{n}集%",
        }
        result = await db.execute(text(_BY_REF_EP_NUMBER_SQL), params)
        row = result.mappings().first()
        if row is not None:
            return _row_to_episode_ref(row)

    params = {"show_id": show_id, "pattern": f"%{ref_clean}%"}
    result = await db.execute(text(_BY_REF_TITLE_SQL), params)
    row = result.mappings().first()
    return _row_to_episode_ref(row) if row is not None else None


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
