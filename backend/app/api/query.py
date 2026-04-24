import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.show import Show
from app.schemas.query import (
    ChatResponse,
    ChunkHit,
    QueryRequest,
    SearchResponse,
)
from app.services import rag
from app.services.embedding import embed_texts
from app.services.llm_config import (
    LLMNotConfigured,
    get_answer_client,
    get_config,
    get_rewrite_client,
    require_keys_present,
)
from app.services.rag import ChunkHit as RagHit

router = APIRouter(tags=["query"])


@router.post("/shows/{show_id}/query")
async def query_show(
    show_id: uuid.UUID,
    payload: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse | ChatResponse:
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show 不存在")

    history = [m.model_dump() for m in payload.messages[-rag.HISTORY_WINDOW:]]

    if payload.mode == "search":
        query_embedding = await asyncio.to_thread(embed_texts, [payload.question])
        hits = await rag.retrieve(db, show_id, query_embedding[0])
        return SearchResponse(results=[_to_schema_hit(h) for h in hits])

    try:
        cfg = await get_config(db)
        require_keys_present(cfg)
    except LLMNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if history:
        rewrite_client, rewrite_model = get_rewrite_client(cfg)
        rewritten = await asyncio.to_thread(
            rag.rewrite_question,
            rewrite_client,
            rewrite_model,
            history,
            payload.question,
        )
    else:
        rewritten = payload.question

    query_embedding = await asyncio.to_thread(embed_texts, [rewritten])
    hits = await rag.retrieve(db, show_id, query_embedding[0])

    answer_client, answer_model = get_answer_client(cfg)
    answer_text, used_ids = await asyncio.to_thread(
        rag.answer_with_chunks,
        answer_client,
        answer_model,
        history,
        payload.question,
        hits,
    )

    if used_ids:
        used_set = set(used_ids)
        cited_hits = [
            h for h in hits
            if f"ep:{h.episode_id}@{h.start_time:.2f}" in used_set
        ]
        if not cited_hits:
            cited_hits = hits
    else:
        cited_hits = hits

    return ChatResponse(
        answer=answer_text,
        citations=[_to_schema_hit(h) for h in cited_hits],
    )


def _to_schema_hit(hit: RagHit) -> ChunkHit:
    return ChunkHit(
        episode_id=hit.episode_id,
        episode_title=hit.episode_title,
        start_time=hit.start_time,
        end_time=hit.end_time,
        text=hit.text,
        distance=hit.distance,
    )
