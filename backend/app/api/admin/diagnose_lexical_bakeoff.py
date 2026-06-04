"""Admin endpoint: lexical-mismatch query-rewrite bake-off.

change: lexical-mismatch-query-rewrite-bakeoff (EQ3b family).

Sibling of `diagnose_prefilter.py`. The existing prefilter-rank endpoint hard-
codes the dataset's original question (diagnose_prefilter.py:146/169/174) and so
cannot inject a rewritten query. This endpoint adds an `arm` parameter: for each
item it runs the arm's rewrite (control / query-expansion / hyde / multi-vector)
in the backend service layer, feeds the resulting retrieve plans into the shared
`rag.retrieve_hybrid`, merges plans by each chunk's best (min) rank across plans,
and reports the 1-based prefilter-rank of each GT chunk plus the arm's cost.

require_admin gated (inherited from the admin router), SELECT-only. The existing
`/admin/diagnose/prefilter-rank` behaviour is untouched.

Body:
    { "arm": "query-expansion", "items": ["b20","b23"], "top_n": 200, "show_id": "<uuid?>" }
"""
from __future__ import annotations

from typing import Any

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services import rag
from app.services.ai_step_resolver import get_step_config
from app.services.lexical_bakeoff_arms import ARMS, apply_arm

# Reuse the prefilter-rank helpers verbatim so ranking semantics stay identical.
from app.api.admin.diagnose_prefilter import (
    DEFAULT_SHOW_ID,
    _DEFAULT_WINDOW_S,
    _cutoff_label,
    _CUTOFFS,
    _derive_prefilter_episodes,
    _load_items_indexed,
    _match_rank,
)

router = APIRouter(prefix="/diagnose", tags=["admin-diagnose"])


class BakeoffRequest(BaseModel):
    arm: str = Field(default="control")
    mini_set_ids: list[str] = Field(default_factory=lambda: ["b20", "b23"])
    items: list[str] | None = None
    top_n: int = Field(default=200, ge=5, le=500)
    show_id: str = DEFAULT_SHOW_ID

    def resolved_items(self) -> list[str]:
        return self.items if self.items else self.mini_set_ids


def _merge_plans_by_min_rank(plan_rankings: list[list]) -> list[tuple[str, float]]:
    """Merge per-plan hit lists: each chunk keeps its best (lowest) rank.

    For single-plan arms this is just that plan's order. For multi-vector
    (N plans) a chunk surfacing high in any sub-query wins — max-similarity
    aggregation expressed as min-rank, without touching retrieve_hybrid.
    """
    best: dict[tuple[str, float], tuple[int, Any]] = {}
    for hits in plan_rankings:
        for idx, h in enumerate(hits):
            key = (str(h.episode_id), round(float(h.start_time), 2))
            if key not in best or idx < best[key][0]:
                best[key] = (idx, h)
    merged = [h for _, h in sorted(best.values(), key=lambda x: x[0])]
    return [(str(h.episode_id), float(h.start_time)) for h in merged]


@router.post("/lexical-bakeoff")
async def diagnose_lexical_bakeoff(
    req: BakeoffRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if req.arm not in ARMS:
        return {"error": f"unknown arm {req.arm!r}; expected one of {list(ARMS)}"}

    items_by_id = _load_items_indexed()
    show_id = uuid.UUID(req.show_id)
    embed_step = await get_step_config(db, "embedding")

    out: list[dict[str, Any]] = []
    for iid in req.resolved_items():
        try:
            item = items_by_id.get(iid)
            if item is None:
                out.append({"item_id": iid, "error": "not in dataset"})
                continue

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

            arm_result = await apply_arm(req.arm, question, db, embed_step)

            plan_rankings = []
            for plan in arm_result.plans:
                hits = await rag.retrieve_hybrid(
                    db,
                    show_id=show_id,
                    query_embedding=plan.embedding,
                    question=plan.lexical_question,
                    k=req.top_n,
                    episode_id_filter=prefilter_eps,
                )
                plan_rankings.append(hits)
            retrieved = _merge_plans_by_min_rank(plan_rankings)

            gt_ranks: list[dict[str, Any]] = []
            for cid in gt_must:
                rank = _match_rank(cid, retrieved, _DEFAULT_WINDOW_S)
                gt_ranks.append({
                    "gt_chunk_id": cid, "kind": "must", "rank": rank,
                    "cutoff_in": _cutoff_label(rank, req.top_n),
                })
            for cid in gt_either:
                rank = _match_rank(cid, retrieved, _DEFAULT_WINDOW_S)
                gt_ranks.append({
                    "gt_chunk_id": cid, "kind": "either", "rank": rank,
                    "cutoff_in": _cutoff_label(rank, req.top_n),
                })

            bucket_counts = {f"top-{c}": 0 for c in _CUTOFFS}
            bucket_counts["miss"] = 0
            for gr in gt_ranks:
                bucket_counts[gr["cutoff_in"]] += 1

            out.append({
                "item_id": iid,
                "arm": req.arm,
                "question": question,
                "top_n": req.top_n,
                "retrieved_count": len(retrieved),
                "gt_total": len(gt_ranks),
                "gt_ranks": gt_ranks,
                "bucket_counts": bucket_counts,
                "cost": {
                    "extra_llm_calls": arm_result.extra_llm_calls,
                    "latency_ms": round(arm_result.llm_ms, 1),
                },
                "rewrite_debug": arm_result.rewrite_debug,
            })
        except Exception as exc:  # per-item isolation: never 500 the whole batch
            out.append({"item_id": iid, "arm": req.arm, "error": f"{type(exc).__name__}: {exc}"})

    return {"arm": req.arm, "items": out}
