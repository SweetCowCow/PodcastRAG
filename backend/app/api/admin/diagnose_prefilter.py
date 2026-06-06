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
from app.services.hyde_retrieval import resolve_semantic_embedding

# Reuse the chunk_id parser used by chunk_recall grader / rrf_sweep.
_CHUNK_RE = re.compile(r"^ep:([0-9a-f-]+)@(\d+\.\d+)$")
_DEFAULT_WINDOW_S = 10.0

DEFAULT_SHOW_ID = "45fc2462-17cf-42f5-98a7-68fe1a222228"
DATASET_PATH = (
    Path(__file__).resolve().parents[3] / "eval" / "datasets" / "extended-multi-turn-40.json"
)

_CUTOFFS = (5, 20, 50, 100, 200, 500)


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
    # `items` is the preferred parameter name (b23-dataset-and-retrieval-rca-fix
    # Phase 3); `mini_set_ids` is preserved as an alias for prior callers.
    mini_set_ids: list[str] = Field(default_factory=lambda: ["b20", "b21", "b23"])
    items: list[str] | None = None
    top_n: int = Field(default=100, ge=5, le=500)
    include_chunking_context: bool = False
    show_id: str = DEFAULT_SHOW_ID

    def resolved_items(self) -> list[str]:
        return self.items if self.items else self.mini_set_ids


router = APIRouter(prefix="/diagnose", tags=["admin-diagnose"])


@router.post("/prefilter-rank")
async def diagnose_prefilter_rank(
    req: DiagnoseRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    items_by_id = _load_items_indexed()
    show_id = uuid.UUID(req.show_id)
    embed_step = await get_step_config(db, "embedding")

    out: list[dict[str, Any]] = []
    for iid in req.resolved_items():
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

        # hyde-retrieval-landing: embed via the flag-gated helper so an A/B run
        # (enable_hyde_retrieval off vs on) measures the LANDED path. Flag off →
        # resolve returns base_vec, bit-identical to the prior plain-embed path.
        base_vec = embed_texts([question], embed_step)[0]
        hyde = await resolve_semantic_embedding(db, question, base_vec, embed_step)
        hits = await rag.retrieve_hybrid(
            db,
            show_id=show_id,
            query_embedding=hyde.semantic_vec,
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

        # Optional chunking-context: for each GT chunk, emit the surrounding
        # ±2 chunks in the retrieved pool (by index near the matched rank,
        # or "missing" if GT itself is absent) plus the GT chunk's start_time.
        # Used by Phase 3 diagnostic to inspect chunking-boundary issues.
        if req.include_chunking_context:
            chunking_context: list[dict[str, Any]] = []
            for gr in gt_ranks:
                gt_cid = gr["gt_chunk_id"]
                parsed = _parse_chunk_id(gt_cid)
                gt_ep = parsed[0] if parsed else None
                gt_st = parsed[1] if parsed else None
                rank = gr["rank"]
                neighbors: list[dict[str, Any]] = []
                if rank is not None:
                    lo = max(0, rank - 3)  # rank is 1-based; show ±2 around rank-1
                    hi = min(len(hits), rank + 2)
                    for i in range(lo, hi):
                        h = hits[i]
                        neighbors.append({
                            "rank": i + 1,
                            "episode_id": str(h.episode_id),
                            "start_time": float(h.start_time),
                            "text_preview": (getattr(h, "text", "") or "")[:200],
                            "is_gt": (i + 1) == rank,
                        })
                else:
                    # GT miss: list 3 closest retrieved chunks from the same episode
                    same_ep = [
                        (i, h) for i, h in enumerate(hits)
                        if gt_ep and str(h.episode_id) == gt_ep
                    ]
                    same_ep.sort(
                        key=lambda x: abs(float(x[1].start_time) - (gt_st or 0))
                    )
                    for i, h in same_ep[:3]:
                        neighbors.append({
                            "rank": i + 1,
                            "episode_id": str(h.episode_id),
                            "start_time": float(h.start_time),
                            "text_preview": (getattr(h, "text", "") or "")[:200],
                            "is_gt": False,
                        })
                chunking_context.append({
                    "gt_chunk_id": gt_cid,
                    "gt_episode_id": gt_ep,
                    "gt_start_time": gt_st,
                    "rank": rank,
                    "neighbors": neighbors,
                })
        else:
            chunking_context = None

        item_out = {
            "item_id": iid,
            "question": question,
            "top_n": req.top_n,
            "retrieved_count": len(hits),
            "prefilter_episode_count": len(prefilter_eps),
            "gt_total": len(gt_ranks),
            "gt_ranks": gt_ranks,
            "bucket_counts": bucket_counts,
            # hyde-retrieval-landing A/B: lets the harness verify the env flag
            # actually took effect (used_hyde must be True on the "on" run) and
            # record the generated HyDE text sample per item.
            "used_hyde": hyde.used_hyde,
            "hyde_text": hyde.hyde_text,
            "extra_llm_calls": hyde.extra_llm_calls,
        }
        if chunking_context is not None:
            item_out["chunking_context"] = chunking_context
        out.append(item_out)

    return {"items": out}
