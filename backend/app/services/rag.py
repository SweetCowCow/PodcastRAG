"""RAG retrieval + answer pipeline.

Retrieval is hybrid (semantic pgvector + lexical PG tsvector) combined via
Reciprocal Rank Fusion (RRF, k=60) and run as a single SQL statement per
side. We retrieve from `transcript_chunks` and `episode_description_chunks`
in parallel and merge by RRF score before returning the top-K.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import api_health, tokenizer
from app.services.llm_prompts import Lang, render_answer_prompt

RETRIEVAL_TOP_K = 8
RRF_K = 60
RRF_PER_SIDE = 50
DESCRIPTION_CAP = 3
ROUTE_EPISODES_K = 10
HISTORY_WINDOW = 10

REWRITE_SYSTEM_PROMPT = (
    "You rewrite a follow-up question into a standalone question, preserving the "
    "original intent and language. Use conversation history only to resolve "
    "pronouns and implicit references. Output ONLY the rewritten question, no "
    "preamble."
)

# R2.1 Decision 4: the answer prompt now lives in `app.services.llm_prompts`
# and enumerates sources as `[1] [2] [3]…`. The legacy single-template constant
# is removed; callers should use `render_answer_prompt(chunks, lang)`.


@dataclass
class ChunkHit:
    episode_id: uuid.UUID
    episode_title: str
    start_time: float
    end_time: float
    text: str
    distance: float | None = None
    chunk_id: uuid.UUID | None = None
    source: Literal["transcript", "description"] = "transcript"
    rrf_score: float = 0.0
    # R2.1 citation infra fields, populated by `enrich_hits()` after retrieval.
    # Default to empty so retrieval-only callers (eval scripts, etc.) keep
    # working without enrichment.
    before_text: str = ""
    after_text: str = ""
    highlights: str = ""
    ai_summary_excerpt: str = ""
    # R2.1 followup: full (untruncated) ai_summary used by SourceCard
    # "expand" toggle. None when the episode has no ai_summary.
    ai_summary_full: str | None = None


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _build_ts_query(question: str) -> str | None:
    """Tokenise via jieba and produce a `to_tsquery('simple', ...)` string.

    Strips pure-punctuation tokens and single-character non-CJK tokens. Joins
    remaining tokens with ` & `. Returns None when nothing usable is left.
    """
    tokens = tokenizer.tokenize(question)
    show_name_terms = tokenizer.get_show_name_terms()
    cleaned: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if re.fullmatch(r"\W+", tok):
            continue
        # tsquery operators: escape `&|!()<:>`
        tok = re.sub(r"[&|!()<:>\\]", " ", tok).strip()
        if not tok:
            continue
        # Drop tokens flagged as show-name in tokenizer_custom_terms — these
        # are too generic to discriminate (e.g. show name appears across
        # every casual mention episode, drowning the actual answer chunk).
        # Embedding side gets the full question text so semantic signal is
        # preserved.
        if tok in show_name_terms:
            continue
        cleaned.append(tok)
    if not cleaned:
        return None
    # OR-join across multi-char tokens. Eval bake-off (this-not-that-cool, k=5,
    # window=30s, 48 items):
    #   v1 ` & ` keep 1-char:  Recall@5 4.76% — lexical CTE empty (collapsed
    #                          to pure semantic baseline)
    #   v2 ` | ` keep 1-char:  Recall@5 3.57% — particles flood lexical pool,
    #                          comprehension drops to 0%, latency 5.5s
    #   v3 ` & ` drop 1-char:  Recall@5 4.76% — STILL lexical-empty: a podcast
    #                          chunk rarely contains all question entities
    #                          simultaneously (instrumented: 0 chunks match
    #                          `節目名 & 這又沒有很屌 & 怎麼` AND query)
    #   v4 ` | ` drop 1-char:  this version — OR over multi-char tokens lets
    #                          lexical actually contribute; ts_rank weighs
    #                          rare matches so entity-dense chunks lift.
    return " | ".join(cleaned)


_TRANSCRIPT_RRF_SQL = """
WITH semantic AS (
    SELECT c.id AS chunk_id,
           ROW_NUMBER() OVER (
               ORDER BY c.embedding <=> CAST(:query_embedding AS vector)
           ) AS rank_s
    FROM transcript_chunks c
    JOIN transcripts t ON t.id = c.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE e.show_id = :show_id
      AND t.status = 'completed'
      AND c.embedding IS NOT NULL
      {episode_filter}
    LIMIT :per_side
),
lexical AS (
    SELECT c.id AS chunk_id,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(c.text_tsvector, to_tsquery('simple', :ts_query)) DESC
           ) AS rank_l
    FROM transcript_chunks c
    JOIN transcripts t ON t.id = c.transcript_id
    JOIN episodes e ON e.id = t.episode_id
    WHERE e.show_id = :show_id
      AND t.status = 'completed'
      AND c.text_tsvector IS NOT NULL
      AND c.text_tsvector @@ to_tsquery('simple', :ts_query)
      {episode_filter}
    LIMIT :per_side
),
combined AS (
    SELECT COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
           1.0 / (:rrf_k + COALESCE(s.rank_s, 999))
         + 1.0 / (:rrf_k + COALESCE(l.rank_l, 999)) AS rrf_score
    FROM semantic s
    FULL OUTER JOIN lexical l USING (chunk_id)
)
SELECT cb.chunk_id,
       cb.rrf_score,
       c.start_time,
       c.end_time,
       c.text,
       e.id AS episode_id,
       e.title AS episode_title
FROM combined cb
JOIN transcript_chunks c ON c.id = cb.chunk_id
JOIN transcripts t ON t.id = c.transcript_id
JOIN episodes e ON e.id = t.episode_id
ORDER BY cb.rrf_score DESC
LIMIT :k
"""

_TRANSCRIPT_SEMANTIC_ONLY_SQL = """
SELECT c.id AS chunk_id,
       c.embedding <=> CAST(:query_embedding AS vector) AS distance,
       c.start_time,
       c.end_time,
       c.text,
       e.id AS episode_id,
       e.title AS episode_title
FROM transcript_chunks c
JOIN transcripts t ON t.id = c.transcript_id
JOIN episodes e ON e.id = t.episode_id
WHERE e.show_id = :show_id
  AND t.status = 'completed'
  AND c.embedding IS NOT NULL
  {episode_filter}
ORDER BY distance
LIMIT :k
"""

_DESC_RRF_SQL = """
WITH semantic AS (
    SELECT d.id AS chunk_id,
           ROW_NUMBER() OVER (
               ORDER BY d.embedding <=> CAST(:query_embedding AS vector)
           ) AS rank_s
    FROM episode_description_chunks d
    JOIN episodes e ON e.id = d.episode_id
    WHERE e.show_id = :show_id
      AND d.embedding IS NOT NULL
      {episode_filter}
    LIMIT :per_side
),
lexical AS (
    SELECT d.id AS chunk_id,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(d.text_tsvector, to_tsquery('simple', :ts_query)) DESC
           ) AS rank_l
    FROM episode_description_chunks d
    JOIN episodes e ON e.id = d.episode_id
    WHERE e.show_id = :show_id
      AND d.text_tsvector IS NOT NULL
      AND d.text_tsvector @@ to_tsquery('simple', :ts_query)
      {episode_filter}
    LIMIT :per_side
),
combined AS (
    SELECT COALESCE(s.chunk_id, l.chunk_id) AS chunk_id,
           1.0 / (:rrf_k + COALESCE(s.rank_s, 999))
         + 1.0 / (:rrf_k + COALESCE(l.rank_l, 999)) AS rrf_score
    FROM semantic s
    FULL OUTER JOIN lexical l USING (chunk_id)
)
SELECT cb.chunk_id,
       cb.rrf_score,
       d.text,
       e.id AS episode_id,
       e.title AS episode_title
FROM combined cb
JOIN episode_description_chunks d ON d.id = cb.chunk_id
JOIN episodes e ON e.id = d.episode_id
ORDER BY cb.rrf_score DESC
LIMIT :k
"""

_DESC_SEMANTIC_ONLY_SQL = """
SELECT d.id AS chunk_id,
       d.embedding <=> CAST(:query_embedding AS vector) AS distance,
       d.text,
       e.id AS episode_id,
       e.title AS episode_title
FROM episode_description_chunks d
JOIN episodes e ON e.id = d.episode_id
WHERE e.show_id = :show_id
  AND d.embedding IS NOT NULL
  {episode_filter}
ORDER BY distance
LIMIT :k
"""

_ROUTE_EPISODES_SQL = """
SELECT e.id AS episode_id
FROM episode_description_chunks d
JOIN episodes e ON e.id = d.episode_id
WHERE e.show_id = :show_id
  AND d.embedding IS NOT NULL
ORDER BY d.embedding <=> CAST(:query_embedding AS vector)
LIMIT :k
"""


def _episode_filter_clause(table_alias: str, params: dict, eps: list[uuid.UUID] | None) -> str:
    """Build the optional `AND <alias>.id = ANY(:episode_ids)` clause and bind."""
    if not eps:
        return ""
    params["episode_ids"] = [str(e) for e in eps]
    return f"AND {table_alias}.id = ANY(CAST(:episode_ids AS uuid[]))"


async def retrieve(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    question: str = "",
    k: int = RETRIEVAL_TOP_K,
    episode_id_filter: list[uuid.UUID] | None = None,
) -> list[ChunkHit]:
    """Hybrid (RRF) retrieval over `transcript_chunks` for one show.

    If the question yields no usable lexical query, falls back to
    semantic-only ranking. Optional `episode_id_filter` restricts both
    semantic and lexical CTEs to the given episode set (used by the
    R3.2 two-layer routing flow).
    """
    ts_query = _build_ts_query(question) if question else None

    base_params: dict = {
        "query_embedding": _vector_literal(query_embedding),
        "show_id": show_id,
        "k": k,
    }
    ep_filter = _episode_filter_clause("e", base_params, episode_id_filter)

    if ts_query:
        sql = text(_TRANSCRIPT_RRF_SQL.format(episode_filter=ep_filter))
        base_params["ts_query"] = ts_query
        base_params["per_side"] = RRF_PER_SIDE
        base_params["rrf_k"] = RRF_K
        result = await db.execute(sql, base_params)
        return [
            ChunkHit(
                chunk_id=row["chunk_id"],
                episode_id=row["episode_id"],
                episode_title=row["episode_title"],
                start_time=float(row["start_time"]),
                end_time=float(row["end_time"]),
                text=row["text"],
                rrf_score=float(row["rrf_score"]),
                source="transcript",
            )
            for row in result.mappings()
        ]

    # No lexical signal — fall back to pure semantic.
    sql = text(_TRANSCRIPT_SEMANTIC_ONLY_SQL.format(episode_filter=ep_filter))
    result = await db.execute(sql, base_params)
    return [
        ChunkHit(
            chunk_id=row["chunk_id"],
            episode_id=row["episode_id"],
            episode_title=row["episode_title"],
            start_time=float(row["start_time"]),
            end_time=float(row["end_time"]),
            text=row["text"],
            distance=float(row["distance"]),
            source="transcript",
        )
        for row in result.mappings()
    ]


async def retrieve_descriptions(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    question: str = "",
    k: int = RETRIEVAL_TOP_K,
    episode_id_filter: list[uuid.UUID] | None = None,
) -> list[ChunkHit]:
    """Hybrid (RRF) retrieval over `episode_description_chunks` for one show.

    Description hits carry `source='description'` and zero start/end times
    so client-side "play from this time" UI can skip the affordance.
    """
    ts_query = _build_ts_query(question) if question else None

    base_params: dict = {
        "query_embedding": _vector_literal(query_embedding),
        "show_id": show_id,
        "k": k,
    }
    ep_filter = _episode_filter_clause("e", base_params, episode_id_filter)

    if ts_query:
        sql = text(_DESC_RRF_SQL.format(episode_filter=ep_filter))
        base_params["ts_query"] = ts_query
        base_params["per_side"] = RRF_PER_SIDE
        base_params["rrf_k"] = RRF_K
        result = await db.execute(sql, base_params)
        return [
            ChunkHit(
                chunk_id=row["chunk_id"],
                episode_id=row["episode_id"],
                episode_title=row["episode_title"],
                start_time=0.0,
                end_time=0.0,
                text=row["text"],
                rrf_score=float(row["rrf_score"]),
                source="description",
            )
            for row in result.mappings()
        ]

    sql = text(_DESC_SEMANTIC_ONLY_SQL.format(episode_filter=ep_filter))
    result = await db.execute(sql, base_params)
    return [
        ChunkHit(
            chunk_id=row["chunk_id"],
            episode_id=row["episode_id"],
            episode_title=row["episode_title"],
            start_time=0.0,
            end_time=0.0,
            text=row["text"],
            distance=float(row["distance"]),
            source="description",
        )
        for row in result.mappings()
    ]


def _should_skip_routing(question: str) -> bool:
    """True when the question is too short to route reliably.

    Routing relies on description embedding similarity. Questions with
    fewer than 2 multi-char (length>=2) jieba tokens (e.g. just '迪拉胖')
    yield poor embedding signal — we'd rather search the whole show.
    """
    if not question or not question.strip():
        return True
    tokens = tokenizer.tokenize(question)
    multi_char = [t for t in tokens if len(t) >= 2]
    return len(multi_char) < 2


async def route_episodes(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    k: int = ROUTE_EPISODES_K,
) -> list[uuid.UUID]:
    """First-layer routing: top-k episode_id by description embedding cosine."""
    sql = text(_ROUTE_EPISODES_SQL)
    result = await db.execute(
        sql,
        {
            "query_embedding": _vector_literal(query_embedding),
            "show_id": show_id,
            "k": k,
        },
    )
    return [row["episode_id"] for row in result.mappings()]


async def retrieve_hybrid(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    question: str = "",
    k: int = RETRIEVAL_TOP_K,
    episode_id_filter: list[uuid.UUID] | None = None,
) -> list[ChunkHit]:
    """Run transcript + description retrieval and merge by RRF score.

    Applies DESCRIPTION_CAP: at most `DESCRIPTION_CAP` description hits in
    the returned top-K. Excess description hits are replaced (in rank
    order) by the next-best transcript hits if any are available.
    """
    transcript_hits = await retrieve(
        db, show_id, query_embedding, question, k=k, episode_id_filter=episode_id_filter
    )
    desc_hits = await retrieve_descriptions(
        db, show_id, query_embedding, question, k=k, episode_id_filter=episode_id_filter
    )

    # Merge by RRF score (existing behaviour).
    seen: set[uuid.UUID] = set()
    ranked: list[ChunkHit] = []
    for h in sorted(
        transcript_hits + desc_hits,
        key=lambda x: (x.rrf_score, -(x.distance or 0.0)),
        reverse=True,
    ):
        if h.chunk_id and h.chunk_id in seen:
            continue
        if h.chunk_id:
            seen.add(h.chunk_id)
        ranked.append(h)

    # Apply DESCRIPTION_CAP: at most N description hits, prefer transcript
    # to fill the rest. If transcripts run out, fall back to filling with
    # extra description hits (cap waived).
    final: list[ChunkHit] = []
    desc_count = 0
    extras: list[ChunkHit] = []
    for h in ranked:
        if len(final) >= k:
            break
        if h.source == "description":
            if desc_count < DESCRIPTION_CAP:
                final.append(h)
                desc_count += 1
            else:
                extras.append(h)
        else:
            final.append(h)
    # If we have spare slots and only extras left, use them (cap waiver).
    while len(final) < k and extras:
        final.append(extras.pop(0))
    return final


# ---------------------------------------------------------------------------
# R2.1 citation infra: source enrichment helpers
# ---------------------------------------------------------------------------
#
# `enrich_hits()` augments a list of `ChunkHit` returned from retrieval with
# four extra fields that the frontend SourceCard renders:
#
#   - before_text: concatenated text of up to 2 preceding `transcript_segments`
#   - after_text:  concatenated text of up to 2 following `transcript_segments`
#   - highlights:  `ts_headline()` output wrapping query-token matches in
#                  `<mark>...</mark>` tags (no other HTML)
#   - ai_summary_excerpt: first 60 chars of the episode's `ai_summary`, with a
#                  trailing `…` if truncated
#
# Description-source hits get empty before/after_text (descriptions have no
# segment-level neighbours per the spec), but their `highlights` are still
# computed against the description text.
#
# We compute jieba tokens *once* per call (using `tokenizer.tokenize`) and feed
# the same `to_tsquery('simple', ...)` string used by RRF retrieval so that
# highlight tokens line up with what was actually retrieved.

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


def _chat_with_tracker(client: OpenAI, **kwargs):
    start_ns = time.monotonic_ns()
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:
        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        http_status = getattr(exc, "status_code", None)
        api_health.record(
            "openai_chat",
            ok=False,
            duration_ms=duration_ms,
            error_category=api_health.classify_error(exc, http_status),
            http_status=http_status,
        )
        raise
    duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
    api_health.record(
        "openai_chat", ok=True, duration_ms=duration_ms, http_status=200
    )
    return resp


def rewrite_question(
    client: OpenAI,
    model: str,
    messages: list[dict],
    question: str,
) -> str:
    history = messages[-HISTORY_WINDOW:]
    chat_messages = [{"role": "system", "content": REWRITE_SYSTEM_PROMPT}]
    chat_messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    chat_messages.append({"role": "user", "content": question})

    resp = _chat_with_tracker(client, model=model, messages=chat_messages)
    return (resp.choices[0].message.content or "").strip() or question


def _hit_key(hit: ChunkHit) -> str:
    if hit.source == "description":
        return f"desc:{hit.episode_id}"
    return f"ep:{hit.episode_id}@{hit.start_time:.2f}"


def answer_with_chunks(
    client: OpenAI,
    model: str,
    messages: list[dict],
    question: str,
    chunks: list[ChunkHit],
    lang: Lang = "zh",
) -> tuple[str, list[str]]:
    """Send the answer prompt to the LLM and parse the JSON reply.

    `lang` controls which bilingual prompt + refusal directive is used
    (Decision 4 + spec scenarios "Empty retrieval triggers explicit refusal").
    """
    import json as _json

    history = messages[-HISTORY_WINDOW:]
    rendered_chunks = [
        (_hit_key(c), c.episode_title, c.text) for c in chunks
    ]
    system_prompt = render_answer_prompt(rendered_chunks, lang=lang)

    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    chat_messages.append({"role": "user", "content": question})

    resp = _chat_with_tracker(
        client,
        model=model,
        messages=chat_messages,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()

    try:
        parsed = _json.loads(raw)
        answer = parsed["answer"]
        used_ids = [str(k) for k in parsed.get("used_chunk_ids", [])]
        return answer, used_ids
    except (ValueError, KeyError):
        return raw, []
