"""RAG result enrichment.

Post-retrieval enrichment of ChunkHit objects: context segments, ts_headline
highlights, and AI-summary excerpts for the SourceCard UI. Depends on rag_sql
for the lexical query used to drive ts_headline.
"""
from __future__ import annotations

import re
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import tokenizer
from app.services.rag_sql import _build_ts_query
from app.services.rag_types import ChunkHit

__all__ = ["enrich_hits"]


# Headline options: keep the fragment short, single fragment, only `<mark>`.
# `MaxFragments=1` + `MaxWords` cap the output; `StartSel`/`StopSel` lock the
# wrapper tags so no other HTML can leak in.
_TS_HEADLINE_OPTS = (
    "StartSel=<mark>, StopSel=</mark>, "
    "MaxWords=35, MinWords=15, ShortWord=0, "
    "HighlightAll=false, MaxFragments=1, FragmentDelimiter= … "
)

_CONTEXT_SEGMENTS_SQL = """
WITH chunk_meta AS (
    SELECT c.transcript_id,
           c.segment_ids
    FROM transcript_chunks c
    WHERE c.id = :chunk_id
),
anchor AS (
    SELECT s.start_time AS first_start,
           le.end_time AS last_end
    FROM chunk_meta cm
    CROSS JOIN LATERAL (
        SELECT start_time
        FROM transcript_segments
        WHERE id = cm.segment_ids[1]
    ) s
    CROSS JOIN LATERAL (
        SELECT end_time
        FROM transcript_segments
        WHERE id = cm.segment_ids[array_length(cm.segment_ids, 1)]
    ) le
),
prev_segs AS (
    SELECT ts.text, ts.start_time
    FROM transcript_segments ts, chunk_meta cm, anchor a
    WHERE ts.transcript_id = cm.transcript_id
      AND ts.start_time < a.first_start
    ORDER BY ts.start_time DESC
    LIMIT 2
),
next_segs AS (
    SELECT ts.text, ts.start_time
    FROM transcript_segments ts, chunk_meta cm, anchor a
    WHERE ts.transcript_id = cm.transcript_id
      AND ts.start_time > a.last_end
    ORDER BY ts.start_time ASC
    LIMIT 2
)
SELECT
    COALESCE(
        (SELECT string_agg(text, ' ' ORDER BY start_time ASC) FROM prev_segs),
        ''
    ) AS before_text,
    COALESCE(
        (SELECT string_agg(text, ' ' ORDER BY start_time ASC) FROM next_segs),
        ''
    ) AS after_text
"""

# Compute ts_headline against a jieba-tokenised representation of the source
# text. The chunk/description tsvectors were built from a space-joined token
# stream (see description_indexer.py), so we feed the *same* token stream here
# to keep lexeme alignment consistent.
_HEADLINE_SQL = """
SELECT ts_headline(
    'simple',
    :tsv_text,
    to_tsquery('simple', :ts_query),
    :opts
) AS highlight
"""

_AI_SUMMARY_SQL = """
SELECT ai_summary
FROM episodes
WHERE id = :episode_id
"""


def _truncate_ai_summary(summary: str | None, max_chars: int = 60) -> str:
    """Return the first `max_chars` of `summary`, plus `…` if truncated.

    Empty / None input → empty string.
    """
    if not summary:
        return ""
    s = summary.strip()
    if not s:
        return ""
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "…"


_TAG_WHITELIST_RE = re.compile(r"</?(?!mark\b)[a-zA-Z][^>]*>")


def _strip_non_mark_tags(html: str) -> str:
    """Defence-in-depth: strip any tag other than `<mark>`/`</mark>`.

    `ts_headline()` with locked StartSel/StopSel only ever emits the configured
    delimiters, but if the underlying text already contained HTML we make sure
    nothing other than `<mark>` survives.
    """
    if not html:
        return ""
    return _TAG_WHITELIST_RE.sub("", html)


async def _fetch_context_segments(
    db: AsyncSession, chunk_id: uuid.UUID
) -> tuple[str, str]:
    row = (
        await db.execute(text(_CONTEXT_SEGMENTS_SQL), {"chunk_id": chunk_id})
    ).mappings().first()
    if row is None:
        return "", ""
    return row["before_text"] or "", row["after_text"] or ""


async def _fetch_highlight(
    db: AsyncSession, source_text: str, ts_query: str | None
) -> str:
    """Run ts_headline over a jieba-tokenised representation of `source_text`.

    Returns empty string when no usable lexical query is available.
    """
    if not ts_query or not source_text:
        return ""
    tokens = tokenizer.tokenize(source_text)
    tsv_text = " ".join(t for t in tokens if t.strip())
    if not tsv_text:
        return ""
    row = (
        await db.execute(
            text(_HEADLINE_SQL),
            {
                "tsv_text": tsv_text,
                "ts_query": ts_query,
                "opts": _TS_HEADLINE_OPTS,
            },
        )
    ).mappings().first()
    if row is None:
        return ""
    return _strip_non_mark_tags(row["highlight"] or "")


async def _fetch_ai_summary_excerpt(
    db: AsyncSession, episode_id: uuid.UUID
) -> str:
    row = (
        await db.execute(text(_AI_SUMMARY_SQL), {"episode_id": episode_id})
    ).mappings().first()
    if row is None:
        return ""
    return _truncate_ai_summary(row["ai_summary"])


async def _fetch_ai_summary_pair(
    db: AsyncSession, episode_id: uuid.UUID
) -> tuple[str, str | None]:
    """Return (excerpt, full) for an episode's ai_summary in a single query.

    `excerpt` is the 60-char truncated version (or "" when missing).
    `full` is the untruncated stripped string, or None when the episode has
    no ai_summary at all.
    """
    row = (
        await db.execute(text(_AI_SUMMARY_SQL), {"episode_id": episode_id})
    ).mappings().first()
    if row is None:
        return "", None
    raw = row["ai_summary"]
    if not raw:
        return "", None
    stripped = raw.strip()
    if not stripped:
        return "", None
    return _truncate_ai_summary(stripped), stripped


async def enrich_hits(
    db: AsyncSession, hits: list[ChunkHit], question: str
) -> list[ChunkHit]:
    """Populate before/after_text, highlights, and ai_summary_excerpt on hits.

    Mutates each hit in place AND returns the same list so callers can chain.

    Per Decision 1: transcript hits get up-to-2 preceding + up-to-2 following
    `transcript_segments` joined by single spaces. Per Decision 2: highlights
    are produced by PostgreSQL `ts_headline()` against the jieba-tokenised
    text (matching the tsvector built by the indexer). Description hits get
    empty before/after_text per the spec.
    """
    if not hits:
        return hits
    ts_query = _build_ts_query(question) if question else None
    for hit in hits:
        if hit.source == "transcript" and hit.chunk_id is not None:
            hit.before_text, hit.after_text = await _fetch_context_segments(
                db, hit.chunk_id
            )
        else:
            hit.before_text = ""
            hit.after_text = ""
        hit.highlights = await _fetch_highlight(db, hit.text, ts_query)
        excerpt, full = await _fetch_ai_summary_pair(db, hit.episode_id)
        hit.ai_summary_excerpt = excerpt
        hit.ai_summary_full = full
    return hits
