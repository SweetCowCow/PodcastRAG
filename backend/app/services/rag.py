import time
import uuid
from dataclasses import dataclass

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import api_health

RETRIEVAL_TOP_K = 8
HISTORY_WINDOW = 10

REWRITE_SYSTEM_PROMPT = (
    "You rewrite a follow-up question into a standalone question, preserving the "
    "original intent and language. Use conversation history only to resolve "
    "pronouns and implicit references. Output ONLY the rewritten question, no "
    "preamble."
)

ANSWER_SYSTEM_PROMPT_TEMPLATE = (
    "You are answering questions about a podcast show. Answer ONLY based on the "
    "provided transcript chunks. If the chunks don't contain the answer, say so. "
    "Reply in the same language as the user's question.\n\n"
    "You MUST respond with a JSON object in this exact format:\n"
    '{{"answer": "<your answer here>", '
    '"used_chunk_ids": ["ep:<episode_id>@<start_time>", ...]}}\n\n'
    "In used_chunk_ids, list only the chunk keys you actually cited in your answer. "
    "Each chunk key follows the pattern ep:<episode_id>@<start_time> as shown below.\n\n"
    "Transcript chunks:\n{chunks_block}"
)


@dataclass
class ChunkHit:
    episode_id: uuid.UUID
    episode_title: str
    start_time: float
    end_time: float
    text: str
    distance: float


async def retrieve(
    db: AsyncSession,
    show_id: uuid.UUID,
    query_embedding: list[float],
    k: int = RETRIEVAL_TOP_K,
) -> list[ChunkHit]:
    sql = text(
        """
        SELECT c.start_time, c.end_time, c.text,
               c.embedding <=> CAST(:query_embedding AS vector) AS distance,
               e.id AS episode_id, e.title AS episode_title
        FROM transcript_chunks c
        JOIN transcripts t ON t.id = c.transcript_id
        JOIN episodes e ON e.id = t.episode_id
        WHERE e.show_id = :show_id
          AND t.status = 'completed'
        ORDER BY distance
        LIMIT :k
        """
    )
    result = await db.execute(
        sql,
        {
            "query_embedding": _vector_literal(query_embedding),
            "show_id": show_id,
            "k": k,
        },
    )
    hits: list[ChunkHit] = []
    for row in result.mappings():
        hits.append(
            ChunkHit(
                episode_id=row["episode_id"],
                episode_title=row["episode_title"],
                start_time=float(row["start_time"]),
                end_time=float(row["end_time"]),
                text=row["text"],
                distance=float(row["distance"]),
            )
        )
    return hits


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


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
        f"ep:{c.episode_id}@{c.start_time:.2f} ({c.episode_title})\n{c.text}"
        for c in chunks
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
