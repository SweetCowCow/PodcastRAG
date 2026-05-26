"""Admin endpoint: diagnose where GT chunks rank inside the prefiltered pool.

Per change retrieval-cross-episode-chunk-recovery task 1.1 — runs server-side
because local Python can't reach Zeabur internal `db:5432`. require_admin
gated, SELECT-only.

For each item: derives the "ideal" prefilter episode set from the item's own
`ground_truth_chunk_ids_must` (the episodes the GT chunks live in), runs
`rag.retrieve_hybrid` with that filter at `k=top_n`, and reports the 1-based
rank of each GT chunk in the retrieved list. This isolates the
"main-episode-internal ranking" question from topic-extraction noise.

Body:
    { "mini_set_ids": ["b20","b21","b23"], "top_n": 100, "show_id": "<uuid?>" }

Response:
    { "items": [{ "item_id", "top_n", "gt_total", "gt_ranks": [
        { "gt_chunk_id", "rank", "cutoff_in": "top-5|top-20|top-50|top-100|miss" }
      ], "prefilter_episode_count" }] }
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import rag
from app.services.ai_step_resolver import get_step_config
from app.services.embedding import embed_texts

# Reuse the chunk_id parser used by chunk_recall grader / rrf_sweep.
_CHUNK_RE = re.compile(r"^ep:([0-9a-f-]+)@(\d+\.\d+)$")
_DEFAULT_WINDOW_S = 10.0

DEFAULT_SHOW_ID = "45fc2462-17cf-42f5-98a7-68fe1a222228"
DATASET_PATH = (
    Path(__file__).resolve().parents[3] / "eval" / "datasets" / "extended-multi-turn-40.json"
)

_CUTOFFS = (5, 20, 50, 100)


def _parse_chunk_id(cid: str) -> tuple[str, float] | None:
    m = _CHUNK_RE.match(cid)
    return (m.group(1), float(m.group(2))) if m else None


def _match_rank(
    gt_chunk_id: str, retrieved: list[tuple[str, float]], window: float
) -> int | None:
    """Return 1-based rank of the first retrieved hit that matches gt within window. None if absent."""
    parsed = _parse_chunk_id(gt_chunk_id)
    if not parsed:
        return None
    ep_gt, st_gt = parsed
    for idx, (ep, st) in enumerate(retrieved):
        if ep == ep_gt and abs(st - st_gt) <= window:
            return idx + 1
    return None


def _cutoff_label(rank: int | None, top_n: int) -> str:
    if rank is None:
        return "miss"
    for c in _CUTOFFS:
        if c > top_n:
            break
        if rank <= c:
            return f"top-{c}"
    return "miss"


def _load_items_indexed() -> dict[str, dict]:
    if not DATASET_PATH.exists():
        raise HTTPException(status_code=500, detail=f"dataset not found at {DATASET_PATH}")
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return {i["id"]: i for i in data.get("items", [])}


def _derive_prefilter_episodes(item: dict) -> list[uuid.UUID]:
    """Extract unique episode UUIDs from the item's must/either chunk lists."""
    sources: list[str] = []
    sources.extend(item.get("ground_truth_chunk_ids_must") or [])
    sources.extend(item.get("ground_truth_chunk_ids_either") or [])
    eps: list[uuid.UUID] = []
    seen: set[str] = set()
    for cid in sources:
        parsed = _parse_chunk_id(cid)
        if not parsed:
            continue
        ep_str = parsed[0]
        if ep_str in seen:
            continue
        seen.add(ep_str)
        try:
            eps.append(uuid.UUID(ep_str))
        except ValueError:
            continue
    return eps


class DiagnoseRequest(BaseModel):
    mini_set_ids: list[str] = Field(default_factory=lambda: ["b20", "b21", "b23"])
    top_n: int = Field(default=100, ge=5, le=200)
    show_id: str = DEFAULT_SHOW_ID


router = APIRouter(prefix="/diagnose", tags=["admin-diagnose"])


@router.post("/prefilter-rank")
async def diagnose_prefilter_rank(
    req: DiagnoseRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    items_by_id = _load_items_indexed()
    show_id = uuid.UUID(req.show_id)
    embed_step = await get_step_config(db, "embedding")

    out: list[dict[str, Any]] = []
    for iid in req.mini_set_ids:
        item = items_by_id.get(iid)
        if item is None:
            out.append({"item_id": iid, "error": "not in dataset"})
            continue

        # Multi-turn items: use first turn's question and GT.
        scope = item
        if item.get("is_multi_turn"):
            turns = item.get("turns") or []
            scope = turns[0] if turns else item

        question = scope.get("question") or item.get("question")
        gt_must = scope.get("ground_truth_chunk_ids_must") or item.get(
            "ground_truth_chunk_ids_must"
        ) or []
        gt_either = scope.get("ground_truth_chunk_ids_either") or item.get(
            "ground_truth_chunk_ids_either"
        ) or []

        if not question:
            out.append({"item_id": iid, "error": "no question"})
            continue
        if not gt_must and not gt_either:
            out.append({"item_id": iid, "error": "no chunk GT"})
            continue

        prefilter_eps = _derive_prefilter_episodes({
            "ground_truth_chunk_ids_must": gt_must,
            "ground_truth_chunk_ids_either": gt_either,
        })
        if not prefilter_eps:
            out.append({"item_id": iid, "error": "could not derive prefilter episodes"})
            continue

        vec = embed_texts([question], embed_step)[0]
        hits = await rag.retrieve_hybrid(
            db,
            show_id=show_id,
            query_embedding=vec,
            question=question,
            k=req.top_n,
            episode_id_filter=prefilter_eps,
        )
        retrieved = [(str(h.episode_id), float(h.start_time)) for h in hits]

        gt_ranks: list[dict[str, Any]] = []
        for cid in gt_must:
            rank = _match_rank(cid, retrieved, _DEFAULT_WINDOW_S)
            gt_ranks.append({
                "gt_chunk_id": cid,
                "kind": "must",
                "rank": rank,
                "cutoff_in": _cutoff_label(rank, req.top_n),
            })
        for cid in gt_either:
            rank = _match_rank(cid, retrieved, _DEFAULT_WINDOW_S)
            gt_ranks.append({
                "gt_chunk_id": cid,
                "kind": "either",
                "rank": rank,
                "cutoff_in": _cutoff_label(rank, req.top_n),
            })

        # Distribution summary: how many GT chunks fall in each cutoff bucket.
        bucket_counts = {f"top-{c}": 0 for c in _CUTOFFS}
        bucket_counts["miss"] = 0
        for gr in gt_ranks:
            bucket_counts[gr["cutoff_in"]] += 1

        out.append({
            "item_id": iid,
            "question": question,
            "top_n": req.top_n,
            "retrieved_count": len(hits),
            "prefilter_episode_count": len(prefilter_eps),
            "gt_total": len(gt_ranks),
            "gt_ranks": gt_ranks,
            "bucket_counts": bucket_counts,
        })

    return {"items": out}
