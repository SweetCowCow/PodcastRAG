"""Keyword (索引) search service.

Strict-AND multi-term lexical search scoped to a single show, returning
sectioned results:

- **T1** (`chunk-and`): transcript chunks where *every* term matches inside the
  *same* chunk (`text_tsvector @@ to_tsquery('simple', q_and)`).
- **T2** (`episode-and`): episodes where *every* term matches in *at least one*
  of three pools (title / description / transcript) — AND across terms, OR
  across pools.
- **T3** (`or-fallback`): only computed when T1 and T2 are both empty — a loose
  OR query over transcript chunks (≤ 50 hits).

Part of change `keyword-index-mode`. SQL/contract design lives in
`openspec/changes/keyword-index-mode/design.md`.

Query parsing reuses the project jieba tokenizer (`app.services.tokenizer`)
and mirrors the tsquery operator handling used by `rag._build_ts_query`. The
endpoint never parses quote phrases, `OR`, or `-term` exclusion — multi-term
queries are always combined with AND for T1/T2 (OR is only the T3 fallback).
"""
from __future__ import annotations

import asyncio
import re
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import tokenizer

# --- Tunables ---------------------------------------------------------------

#: Hard cap on items returned per section across all paginated calls.
SECTION_HARD_CAP = 100
#: Max hits returned in the T3 OR fallback section.
T3_LIMIT = 50
#: Wall-clock budget for the DB work behind one keyword search.
QUERY_TIMEOUT_SECONDS = 5.0
#: Default T2 collapse threshold, mirrored by the `app_settings` column default.
DEFAULT_T2_COLLAPSE_THRESHOLD = 10

# Tokens that carry no lexical discrimination value. Boolean connector words are
# included because the endpoint deliberately does NOT parse them as operators —
# treating a bare `OR` / `AND` / `NOT` as a literal search term would only ever
# depress recall, so they are dropped as noise. CJK particles are common
# function words that flood the lexical pool without narrowing intent.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "and",
        "or",
        "not",
        "的",
        "了",
        "是",
        "在",
        "和",
        "與",
        "及",
        "或",
        "也",
        "都",
        "就",
        "而",
        "之",
        "跟",
    }
)

# Pure-punctuation tokens (jieba can emit standalone punctuation). For unicode
# strings CJK characters count as word characters, so `\W+` only matches
# punctuation / symbol / whitespace runs — exactly what we want to drop.
_PUNCT_ONLY_RE = re.compile(r"\W+")

# tsquery operators that must not leak into a `to_tsquery('simple', ...)`
# lexeme. We backslash-escape them so the surrounding character stays part of
# the literal lexeme (e.g. `b)c` -> `b\)c`), which keeps the term searchable
# instead of being silently split as `rag._build_ts_query`'s space-replacement
# would do.
_TSQUERY_SPECIAL_RE = re.compile(r"([&|!()<:>\\])")


# --- Errors -----------------------------------------------------------------


class EmptyKeywordQueryError(ValueError):
    """Raised when the query yields no usable terms after tokenization."""


class KeywordSearchTimeoutError(Exception):
    """Raised when the DB work exceeds ``QUERY_TIMEOUT_SECONDS``."""


# --- Query parsing ----------------------------------------------------------


def parse_query(raw: str) -> list[str]:
    """Tokenize ``raw`` into canonical search terms.

    Runs the shared jieba tokenizer, drops punctuation-only tokens and
    stopwords (boolean connectors + CJK particles), and deduplicates while
    preserving first-seen order. Returns ``[]`` for empty / punctuation-only
    input; the caller decides how to treat an empty term list (the endpoint
    maps it to ``422 EMPTY_QUERY``).
    """
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokenizer.tokenize(raw):
        token = token.strip()
        if not token:
            continue
        if _PUNCT_ONLY_RE.fullmatch(token):
            continue
        if token.casefold() in _STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _escape_term(term: str) -> str:
    """Backslash-escape tsquery operator characters in a single lexeme."""
    return _TSQUERY_SPECIAL_RE.sub(r"\\\1", term)


def build_tsquery_and(terms: list[str]) -> str:
    """Join terms with the tsquery AND operator (` & `), escaping operators."""
    return " & ".join(_escape_term(t) for t in terms)


def build_tsquery_or(terms: list[str]) -> str:
    """Join terms with the tsquery OR operator (` | `), escaping operators."""
    return " | ".join(_escape_term(t) for t in terms)


def _compute_hits(text_value: str, terms: list[str]) -> list[dict]:
    """Return per-term character match positions inside ``text_value``.

    Case-insensitive substring scan (CJK has no case but the fold keeps Latin
    terms robust). Only terms with ≥1 occurrence are included.
    """
    haystack = text_value.casefold()
    hits: list[dict] = []
    for term in terms:
        needle = term.casefold()
        if not needle:
            continue
        positions: list[int] = []
        start = 0
        while True:
            idx = haystack.find(needle, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + len(needle)
        if positions:
            hits.append({"term": term, "positions": positions})
    return hits


# --- Section queries --------------------------------------------------------


_T1_SQL = text(
    """
    SELECT c.id          AS chunk_id,
           e.id          AS episode_id,
           e.title       AS episode_title,
           c.start_time  AS start_time,
           c.end_time    AS end_time,
           c.text        AS text
    FROM transcript_chunks c
    JOIN transcripts t ON t.id = c.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE e.show_id = :show_id
      AND t.status = 'completed'
      AND c.text_tsvector IS NOT NULL
      AND c.text_tsvector @@ to_tsquery('simple', :q_and)
    ORDER BY ts_rank(c.text_tsvector, to_tsquery('simple', :q_and)) DESC,
             c.id
    LIMIT :cap
    """
)


async def query_t1(
    db: AsyncSession,
    show_id: uuid.UUID,
    terms: list[str],
    offset: int,
    limit: int,
) -> tuple[list[dict], int]:
    """T1: chunks where every term matches in the same chunk.

    Returns ``(items[offset : offset + limit], total)`` where ``total`` is the
    match count capped at :data:`SECTION_HARD_CAP`.
    """
    if not terms:
        return [], 0
    q_and = build_tsquery_and(terms)
    result = await db.execute(
        _T1_SQL,
        {"show_id": show_id, "q_and": q_and, "cap": SECTION_HARD_CAP},
    )
    rows = result.mappings().all()
    total = len(rows)
    page = rows[offset : offset + limit]
    items = [
        {
            "chunk_id": row["chunk_id"],
            "episode_id": row["episode_id"],
            "episode_title": row["episode_title"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "text": row["text"],
            "hits": _compute_hits(row["text"], terms),
        }
        for row in page
    ]
    return items, total


# Episodes (of a show) where a single term matches in ANY of the three pools.
_T2_TERM_EPISODES_SQL = text(
    """
    SELECT e.id AS episode_id
    FROM episodes e
    WHERE e.show_id = :show_id
      AND e.title_tsvector @@ to_tsquery('simple', :q)
    UNION
    SELECT d.episode_id
    FROM episode_description_chunks d
    JOIN episodes e ON e.id = d.episode_id
    WHERE e.show_id = :show_id
      AND d.text_tsvector @@ to_tsquery('simple', :q)
    UNION
    SELECT e.id
    FROM transcript_chunks c
    JOIN transcripts t ON t.id = c.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE e.show_id = :show_id
      AND t.status = 'completed'
      AND c.text_tsvector @@ to_tsquery('simple', :q)
    """
)

# Per-pool match counts (OR over all terms) for a fixed set of episodes.
_T2_TITLE_COUNT_SQL = text(
    """
    SELECT e.id AS episode_id
    FROM episodes e
    WHERE e.id = ANY(CAST(:episode_ids AS uuid[]))
      AND e.title_tsvector @@ to_tsquery('simple', :q_or)
    """
)
_T2_DESC_COUNT_SQL = text(
    """
    SELECT d.episode_id AS episode_id, count(*) AS n
    FROM episode_description_chunks d
    WHERE d.episode_id = ANY(CAST(:episode_ids AS uuid[]))
      AND d.text_tsvector @@ to_tsquery('simple', :q_or)
    GROUP BY d.episode_id
    """
)
_T2_TX_COUNT_SQL = text(
    """
    SELECT e.id AS episode_id, count(*) AS n
    FROM transcript_chunks c
    JOIN transcripts t ON t.id = c.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE e.id = ANY(CAST(:episode_ids AS uuid[]))
      AND t.status = 'completed'
      AND c.text_tsvector @@ to_tsquery('simple', :q_or)
    GROUP BY e.id
    """
)
_T2_TITLES_SQL = text(
    """
    SELECT e.id AS episode_id, e.title AS episode_title
    FROM episodes e
    WHERE e.id = ANY(CAST(:episode_ids AS uuid[]))
    """
)


async def query_t2(
    db: AsyncSession,
    show_id: uuid.UUID,
    terms: list[str],
    offset: int,
    limit: int,
) -> tuple[list[dict], int]:
    """T2: episodes where every term matches in at least one pool.

    Qualification is AND across terms / OR across pools: for each term we
    collect the set of episodes matching it in title, description, or
    transcript, then intersect across terms. ``pool_counts`` reports, for the
    qualifying episodes, how many rows in each pool match *any* term.

    Returns ``(items[offset : offset + limit], total)`` with ``total`` capped
    at :data:`SECTION_HARD_CAP`.
    """
    if not terms:
        return [], 0

    # AND across terms: intersect per-term episode sets.
    qualified: set[uuid.UUID] | None = None
    for term in terms:
        result = await db.execute(
            _T2_TERM_EPISODES_SQL,
            {"show_id": show_id, "q": _escape_term(term)},
        )
        term_eps = {row[0] for row in result.all()}
        qualified = term_eps if qualified is None else (qualified & term_eps)
        if not qualified:
            return [], 0

    assert qualified is not None
    if not qualified:
        return [], 0

    episode_ids = [str(eid) for eid in qualified]
    q_or = build_tsquery_or(terms)

    title_rows = (
        await db.execute(
            _T2_TITLE_COUNT_SQL, {"episode_ids": episode_ids, "q_or": q_or}
        )
    ).all()
    title_hits = {row[0] for row in title_rows}

    desc_rows = (
        await db.execute(
            _T2_DESC_COUNT_SQL, {"episode_ids": episode_ids, "q_or": q_or}
        )
    ).all()
    desc_counts = {row[0]: row[1] for row in desc_rows}

    tx_rows = (
        await db.execute(
            _T2_TX_COUNT_SQL, {"episode_ids": episode_ids, "q_or": q_or}
        )
    ).all()
    tx_counts = {row[0]: row[1] for row in tx_rows}

    title_rows_all = (
        await db.execute(_T2_TITLES_SQL, {"episode_ids": episode_ids})
    ).all()
    titles = {row[0]: row[1] for row in title_rows_all}

    items_all: list[dict] = []
    for eid in qualified:
        pool_counts = {
            "title": 1 if eid in title_hits else 0,
            "description": int(desc_counts.get(eid, 0)),
            "transcript": int(tx_counts.get(eid, 0)),
        }
        items_all.append(
            {
                "episode_id": eid,
                "episode_title": titles.get(eid, ""),
                "pool_counts": pool_counts,
            }
        )

    # Most-covered episodes first; stable tie-break on title then id.
    items_all.sort(
        key=lambda it: (
            -(
                it["pool_counts"]["title"]
                + it["pool_counts"]["description"]
                + it["pool_counts"]["transcript"]
            ),
            it["episode_title"],
            str(it["episode_id"]),
        )
    )

    total = min(len(items_all), SECTION_HARD_CAP)
    capped = items_all[:SECTION_HARD_CAP]
    page = capped[offset : offset + limit]
    return page, total


_T3_SQL = text(
    """
    SELECT c.id          AS chunk_id,
           e.id          AS episode_id,
           e.title       AS episode_title,
           c.start_time  AS start_time,
           c.end_time    AS end_time,
           c.text        AS text
    FROM transcript_chunks c
    JOIN transcripts t ON t.id = c.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE e.show_id = :show_id
      AND t.status = 'completed'
      AND c.text_tsvector IS NOT NULL
      AND c.text_tsvector @@ to_tsquery('simple', :q_or)
    ORDER BY ts_rank(c.text_tsvector, to_tsquery('simple', :q_or)) DESC,
             c.id
    LIMIT :limit
    """
)


async def query_t3(
    db: AsyncSession,
    show_id: uuid.UUID,
    terms: list[str],
    limit: int = T3_LIMIT,
) -> list[dict]:
    """T3: loose OR fallback over transcript chunks (≤ ``limit`` hits)."""
    if not terms:
        return []
    q_or = build_tsquery_or(terms)
    result = await db.execute(
        _T3_SQL, {"show_id": show_id, "q_or": q_or, "limit": limit}
    )
    rows = result.mappings().all()
    return [
        {
            "chunk_id": row["chunk_id"],
            "episode_id": row["episode_id"],
            "episode_title": row["episode_title"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "text": row["text"],
            "hits": _compute_hits(row["text"], terms),
        }
        for row in rows
    ]


# --- Orchestrator -----------------------------------------------------------


async def _execute_sections(
    db: AsyncSession,
    show_id: uuid.UUID,
    terms: list[str],
    offset_t1: int,
    offset_t2: int,
    limit: int,
    threshold: int,
) -> dict:
    t1_items, t1_total = await query_t1(db, show_id, terms, offset_t1, limit)
    t2_items, t2_total = await query_t2(db, show_id, terms, offset_t2, limit)

    t3: dict | None = None
    # T3 is computed ONLY when both strict sections are empty; otherwise the OR
    # query is never executed (and `t3` stays null).
    if t1_total == 0 and t2_total == 0:
        t3_items = await query_t3(db, show_id, terms)
        t3 = {"section": "or-fallback", "total": len(t3_items), "items": t3_items}

    # Presentation hint only — `t2.items` is always fully populated regardless.
    collapsed = t1_total >= threshold

    return {
        "query": None,  # filled by run_keyword_search (keeps the raw input)
        "terms": terms,
        "mode": "keyword",
        "t1": {"section": "chunk-and", "total": t1_total, "items": t1_items},
        "t2": {
            "section": "episode-and",
            "total": t2_total,
            "collapsed": collapsed,
            "items": t2_items,
        },
        "t3": t3,
    }


async def run_keyword_search(
    db: AsyncSession,
    show_id: uuid.UUID,
    raw_query: str,
    *,
    offset_t1: int = 0,
    offset_t2: int = 0,
    limit: int = 25,
    threshold: int = DEFAULT_T2_COLLAPSE_THRESHOLD,
) -> dict:
    """Run the full keyword search and assemble the sectioned response dict.

    Raises :class:`EmptyKeywordQueryError` when the query tokenizes to nothing
    and :class:`KeywordSearchTimeoutError` when the DB work exceeds
    :data:`QUERY_TIMEOUT_SECONDS`.
    """
    terms = parse_query(raw_query)
    if not terms:
        raise EmptyKeywordQueryError()

    try:
        response = await asyncio.wait_for(
            _execute_sections(
                db, show_id, terms, offset_t1, offset_t2, limit, threshold
            ),
            timeout=QUERY_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise KeywordSearchTimeoutError() from exc

    response["query"] = raw_query
    return response
