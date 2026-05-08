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

ANSWER_SYSTEM_PROMPT_TEMPLATE = (
    "You are answering questions about a podcast show. Answer ONLY based on the "
    "provided sources. If the sources don't contain the answer, say so. "
    "Reply in the same language as the user's question.\n\n"
    "Each source is prefixed with one of:\n"
    "  - ep:<episode_id>@<start_time> for transcript chunks\n"
    "  - desc:<episode_id> for episode description (RSS) chunks\n\n"
    "You MUST respond with a JSON object in this exact format:\n"
    '{{"answer": "<your answer here>", '
    '"used_chunk_ids": ["ep:<episode_id>@<start_time>" or "desc:<episode_id>", ...]}}\n\n'
    "In used_chunk_ids, list only the source keys you actually cited.\n\n"
    "Sources:\n{chunks_block}"
)


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
) -> tuple[str, list[str]]:
    import json as _json

    history = messages[-HISTORY_WINDOW:]
    chunks_block = "\n\n".join(
        f"{_hit_key(c)} ({c.episode_title})\n{c.text}" for c in chunks
    )
    system_prompt = ANSWER_SYSTEM_PROMPT_TEMPLATE.format(chunks_block=chunks_block)

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
