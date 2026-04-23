import uuid
from dataclasses import dataclass

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    "provided transcript chunks. Cite sources using [ep:<episode_id>@<start_time>] "
    "after relevant claims. If the chunks don't contain the answer, say so. Reply "
    "in the same language as the user's question.\n\n"
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

    resp = client.chat.completions.create(model=model, messages=chat_messages)
    return (resp.choices[0].message.content or "").strip() or question


def answer_with_chunks(
    client: OpenAI,
    model: str,
    messages: list[dict],
    question: str,
    chunks: list[ChunkHit],
) -> str:
    history = messages[-HISTORY_WINDOW:]
    chunks_block = "\n\n".join(
        f"[ep:{c.episode_id}@{c.start_time:.2f}] ({c.episode_title})\n{c.text}"
        for c in chunks
    )
    system_prompt = ANSWER_SYSTEM_PROMPT_TEMPLATE.format(chunks_block=chunks_block)

    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    chat_messages.append({"role": "user", "content": question})

    resp = client.chat.completions.create(model=model, messages=chat_messages)
    return (resp.choices[0].message.content or "").strip()
