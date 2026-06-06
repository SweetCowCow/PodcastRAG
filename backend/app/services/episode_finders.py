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
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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


_KNOWN_GUESTS_SQL = """
SELECT DISTINCT jsonb_array_elements_text(guests) AS name
FROM episodes
WHERE show_id = :show_id
  AND jsonb_typeof(guests) = 'array'
  AND jsonb_array_length(guests) > 0
"""

# Cache of known guest-name index per show_id. Each entry stores
# (timestamp, full_names_set, token_to_fullname_map).
# token_to_fullname_map handles jieba-split tokens of multi-word guest names
# (e.g. "Leo 王" stored as one string; jieba tokenises to ["Leo", "王"], so
# we expose {"Leo": "Leo 王", "王": "Leo 王"} for topic-token matching).
# TTL is short so admin guest edits propagate within a few minutes.
_GUEST_NAME_CACHE_TTL_S = 300.0
_guest_name_cache: dict[
    uuid.UUID, tuple[float, frozenset[str], dict[str, str]]
] = {}


async def _known_guest_names(
    db: AsyncSession, show_id: uuid.UUID
) -> tuple[frozenset[str], dict[str, str]]:
    """Return (full_names, token_to_fullname_map) for the show's known guests.

    `full_names` is the set of distinct guest-name strings stored in
    `episodes.guests` JSONB string-arrays. `token_to_fullname_map` maps each
    jieba-tokenised component back to the original full name so the topic-
    dispatch heuristic can match per-token signals (a topic like
    "迪拉 Leo 王" produces tokens ["Leo", "王"] after the length-≥2 filter
    drops the single character; the map lets us recognise both as pointing
    at "Leo 王"). Both the full string and individual tokens are valid keys.

    Result is cached for up to `_GUEST_NAME_CACHE_TTL_S` seconds.
    """
    now = time.monotonic()
    cached = _guest_name_cache.get(show_id)
    if cached is not None and (now - cached[0]) < _GUEST_NAME_CACHE_TTL_S:
        return cached[1], cached[2]
    result = await db.execute(text(_KNOWN_GUESTS_SQL), {"show_id": show_id})
    full = frozenset(row[0] for row in result.fetchall() if row[0])
    token_map: dict[str, str] = {}
    for name in full:
        token_map[name] = name  # full name is always a valid key
        for tok in tokenizer.tokenize(name):
            tok = tok.strip()
            # Skip 1-char tokens for the per-token map (they over-match in
            # heuristic checks; e.g. "王" is too common across many names).
            if tok and len(tok) >= 2 and tok not in TOPIC_STOPWORDS:
                token_map.setdefault(tok, name)
    _guest_name_cache[show_id] = (now, full, token_map)
    return full, token_map


# Guest-index dispatch path (b23-dataset-and-retrieval-rca-fix):
# when ≥2 jieba tokens of the topic match the show's known guest set,
# also pull episodes whose `episodes.guests` JSONB string-array contains
# any of the matched tokens. Returned rows are unioned (dedup) with the
# title / description tsquery results.
_GUEST_DISPATCH_SQL = """
SELECT id, title, published_at, guests, ai_summary
FROM episodes
WHERE show_id = :show_id
  AND guests ?| CAST(:names AS text[])
ORDER BY published_at DESC NULLS LAST
"""


# Transcript-aware candidate source (topic-prefilter-transcript-aware, b23):
# include episodes whose transcript chunks lexically match the topic tsquery,
# so narrative episodes whose answer is buried in speech (title/description
# silent) become candidates. Episodes are ranked by their best chunk's
# ts_rank and capped to :cap to stop a single common token (e.g. a host name
# spoken in most episodes) from selecting the whole show.
_TRANSCRIPT_TOPIC_SQL = """
SELECT e.id, e.title, e.published_at, e.guests, e.ai_summary
FROM episodes e
JOIN transcripts t ON t.episode_id = e.id
JOIN transcript_chunks tc ON tc.transcript_id = t.id
WHERE e.show_id = :show_id
  AND tc.text_tsvector IS NOT NULL
  AND tc.text_tsvector @@ to_tsquery('simple', :tsquery_text)
GROUP BY e.id, e.title, e.published_at, e.guests, e.ai_summary
ORDER BY MAX(ts_rank(tc.text_tsvector, to_tsquery('simple', :tsquery_text))) DESC,
         e.published_at DESC NULLS LAST
LIMIT :cap
"""


def _discriminating_tokens(expanded: list[str]) -> list[str]:
    """Topic tokens that remain after removing show-name terms — the gate
    for the transcript candidate source (≥2 required).

    No host registry exists and a host name is not necessarily present in
    the show title, so only `tokenizer.get_show_name_terms()` (derived from
    `shows.title`) is removed here; host-token noise is absorbed by the
    ts_rank cap instead (topic-prefilter-transcript-aware design D2).
    """
    show_terms = tokenizer.get_show_name_terms()
    return [t for t in expanded if t not in show_terms]


async def find_episodes_by_topic_with_source(
    db: AsyncSession,
    show_id: uuid.UUID,
    topic_terms: list[str],
) -> tuple[list[EpisodeRef], str]:
    """Variant of `find_episodes_by_topic` that also reports which dispatch
    path produced the candidate set: `"topic_index"` (title/description
    tsquery only), `"guest_index"` (guest-name JSONB only), or `"merged"`
    (both contributed distinct episodes).

    The guest-index path is triggered when at least two jieba tokens of the
    topic match the show's known guest set (see b23-dataset-and-retrieval-rca-fix
    case study for rationale). Single-token / zero-match queries preserve the
    prior title / description tsquery behaviour exactly.

    Set `settings.enable_guest_dispatch=False` to globally bypass the
    guest-index dispatch (env rollback toggle; no redeploy needed).
    """
    cleaned = [t.strip() for t in topic_terms if t and t.strip()]
    if not cleaned:
        return [], "topic_index"
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
        return [], "topic_index"

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

    # Guest-index dispatch: ≥2 expanded tokens hit the show's known-guest
    # token map → also run guest SQL and union results. The map lets a
    # multi-token guest name like "Leo 王" be matched by its components
    # (jieba splits "Leo 王" → ["Leo", "王"] in production queries).
    # Done BEFORE the topic SQL so the topic SQL remains the last
    # `db.execute` call (preserves existing tests that inspect
    # `db.execute.call_args` for topic SQL shape).
    guest_eps: list[EpisodeRef] = []
    if getattr(settings, "enable_guest_dispatch", True):
        try:
            _, token_map = await _known_guest_names(db, show_id)
        except (TypeError, AttributeError):
            # Defensive: some unit tests mock db.execute without a real
            # `fetchall` shape. Treat as "no known guests" and skip dispatch.
            token_map = {}
        # Collect distinct FULL guest names this topic touches.
        matched_full = {token_map[tk] for tk in expanded if tk in token_map}
        if len(matched_full) >= 2:
            guest_result = await db.execute(
                text(_GUEST_DISPATCH_SQL),
                {"show_id": show_id, "names": list(matched_full)},
            )
            guest_eps = [
                _row_to_episode_ref(row) for row in guest_result.mappings()
            ]

    # Transcript-index dispatch: when the topic has ≥2 discriminating tokens
    # (after show-name removal), also pull episodes whose transcript chunks
    # lexically match, capped by best-chunk ts_rank. Run BEFORE the topic SQL
    # so the topic SQL stays the last `db.execute` call. flag off or <2
    # discriminating tokens → query never runs (candidate set is
    # bit-equivalent to the prior title/description behaviour).
    transcript_eps: list[EpisodeRef] = []
    if getattr(settings, "enable_transcript_topic_prefilter", True):
        if len(_discriminating_tokens(expanded)) >= 2:
            ts_result = await db.execute(
                text(_TRANSCRIPT_TOPIC_SQL),
                {
                    "show_id": show_id,
                    "tsquery_text": tsquery_text,
                    "cap": getattr(settings, "transcript_prefilter_cap", 12),
                },
            )
            transcript_eps = [
                _row_to_episode_ref(row) for row in ts_result.mappings()
            ]

    params = {
        "show_id": show_id,
        "tsquery_text": tsquery_text,
    }
    result = await db.execute(text(_TOPIC_SQL), params)
    topic_eps = [_row_to_episode_ref(row) for row in result.mappings()]

    if not guest_eps and not transcript_eps:
        return topic_eps, "topic_index"

    # Union dedupe by episode_id, preserving order: topic_eps (published_at
    # DESC) first, then guest_eps, then transcript_eps (best-chunk ts_rank
    # DESC). Only entries not already present are appended.
    seen_ids: set[uuid.UUID] = {ep.episode_id for ep in topic_eps}
    merged = list(topic_eps)
    guest_added = 0
    for ep in guest_eps:
        if ep.episode_id not in seen_ids:
            merged.append(ep)
            seen_ids.add(ep.episode_id)
            guest_added += 1
    transcript_added = 0
    for ep in transcript_eps:
        if ep.episode_id not in seen_ids:
            merged.append(ep)
            seen_ids.add(ep.episode_id)
            transcript_added += 1

    # Source label (informational only; nothing branches on it). "merged"
    # when ≥2 sources contribute distinct episodes; otherwise the single
    # contributing source's label.
    contributors = []
    if topic_eps:
        contributors.append("topic")
    if guest_added:
        contributors.append("guest")
    if transcript_added:
        contributors.append("transcript")
    if len(contributors) >= 2:
        return merged, "merged"
    if contributors == ["guest"]:
        return merged, "guest_index"
    if contributors == ["transcript"]:
        return merged, "transcript_index"
    return merged, "topic_index"


async def find_episodes_by_topic(
    db: AsyncSession,
    show_id: uuid.UUID,
    topic_terms: list[str],
) -> list[EpisodeRef]:
    """Episodes whose `episodes.title_tsvector` OR any of its
    `episode_description_chunks.text_tsvector` rows match ANY of
    `topic_terms` (terms OR-joined into the tsquery), unioned with
    guest-name JSONB matches when ≥2 tokens hit the known-guest set.

    Backward-compatible wrapper around `find_episodes_by_topic_with_source`
    that drops the dispatch-source enum. Callers that need the source
    (`search_with_topic_prefilter`) should use the `_with_source` variant
    directly.
    """
    eps, _source = await find_episodes_by_topic_with_source(
        db, show_id, topic_terms
    )
    return eps


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
