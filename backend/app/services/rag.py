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
    cleaned: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if re.fullmatch(r"\W+", tok):
            continue
        if len(tok) == 1 and not re.match(r"[一-鿿]", tok):
            continue
        # tsquery operators: escape `&|!()<:>`
        tok = re.sub(r"[&|!()<:>\\]", " ", tok).strip()
        if not tok:
            continue
        cleaned.append(tok)
    if not cleaned:
        return None
    return " & ".join(cleaned)


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
ORDER BY distance
LIMIT :k
"""


async def retrieve(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    question: str = "",
    k: int = RETRIEVAL_TOP_K,
) -> list[ChunkHit]:
    """Hybrid (RRF) retrieval over `transcript_chunks` for one show.

    If the question yields no usable lexical query, falls back to
    semantic-only ranking — which keeps callers passing pre-computed
    embeddings working even when jieba returns no tokens.
    """
    ts_query = _build_ts_query(question) if question else None

    if ts_query:
        sql = text(_TRANSCRIPT_RRF_SQL)
        result = await db.execute(
            sql,
            {
                "query_embedding": _vector_literal(query_embedding),
                "show_id": show_id,
                "ts_query": ts_query,
                "k": k,
                "per_side": RRF_PER_SIDE,
                "rrf_k": RRF_K,
            },
        )
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
    sql = text(_TRANSCRIPT_SEMANTIC_ONLY_SQL)
    result = await db.execute(
        sql,
        {
            "query_embedding": _vector_literal(query_embedding),
            "show_id": show_id,
            "k": k,
        },
    )
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
) -> list[ChunkHit]:
    """Hybrid (RRF) retrieval over `episode_description_chunks` for one show.

    Description hits carry `source='description'` and zero start/end times
    so client-side "play from this time" UI can skip the affordance.
    """
    ts_query = _build_ts_query(question) if question else None

    if ts_query:
        sql = text(_DESC_RRF_SQL)
        result = await db.execute(
            sql,
            {
                "query_embedding": _vector_literal(query_embedding),
                "show_id": show_id,
                "ts_query": ts_query,
                "k": k,
                "per_side": RRF_PER_SIDE,
                "rrf_k": RRF_K,
            },
        )
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

    sql = text(_DESC_SEMANTIC_ONLY_SQL)
    result = await db.execute(
        sql,
        {
            "query_embedding": _vector_literal(query_embedding),
            "show_id": show_id,
            "k": k,
        },
    )
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


async def retrieve_hybrid(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    question: str = "",
    k: int = RETRIEVAL_TOP_K,
) -> list[ChunkHit]:
    """Run transcript + description retrieval and merge by RRF score."""
    transcript_hits = await retrieve(db, show_id, query_embedding, question, k=k)
    desc_hits = await retrieve_descriptions(
        db, show_id, query_embedding, question, k=k
    )

    seen: set[uuid.UUID] = set()
    merged: list[ChunkHit] = []
    for h in sorted(
        transcript_hits + desc_hits,
        key=lambda x: (x.rrf_score, -(x.distance or 0.0)),
        reverse=True,
    ):
        if h.chunk_id and h.chunk_id in seen:
            continue
        if h.chunk_id:
            seen.add(h.chunk_id)
        merged.append(h)
        if len(merged) >= k:
            break
    return merged


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
