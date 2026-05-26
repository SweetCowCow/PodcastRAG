"""Admin endpoint: RRF weight sweep harness (in-process, read-only).

Per change retrieval-cross-episode-recall-improvement design-drift note:
local DB connections can't reach Zeabur internal `db:5432` hostname, so the
sweep harness runs server-side. require_admin gated. SELECT-only — no DB
writes. Restores RRF_WEIGHTS to original after each candidate.

Body:
  {
    "candidates": [{"chunk": 1.0, "description": 0.85, "title": 0.5}, ...],
    "show_id": "<uuid>",          # optional, defaults baked in
    "mini_set_ids": ["b20", ...]  # optional, defaults baked in
  }

Response:
  {
    "baseline_index": int,        # which candidate index is baseline (description == 0.7)
    "candidates": [
      {
        "weights": {...},
        "per_item": [{"item_id", "score", "must_hits", "must_total", "either_group_hit", "error"?}, ...],
        "cross_episode_recall_mean": float | null,
        "deep_dive_recall_mean": float | null,
      },
      ...
    ]
  }
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.database import get_db
from app.services import rag
from app.services.ai_step_resolver import get_step_config
from app.services.embedding import embed_texts

# Mirror of backend/eval/graders/chunk_recall_grouped.py — duplicated here to
# avoid making backend.app depend on backend.eval. Keep in sync (spec rag-eval-runner
# `chunk_recall_grouped grader` is the source of truth).
import re

_CHUNK_RE = re.compile(r"^ep:([0-9a-f-]+)@(\d+\.\d+)$")
_DEFAULT_WINDOW_S = 10.0


def _parse_chunk_id(cid: str) -> tuple[str, float] | None:
    m = _CHUNK_RE.match(cid)
    return (m.group(1), float(m.group(2))) if m else None


def _chunk_in_retrieved(gt: str, retrieved: list[tuple[str, float]], window: float) -> bool:
    parsed = _parse_chunk_id(gt)
    if not parsed:
        return False
    ep_gt, st_gt = parsed
    return any(ep == ep_gt and abs(st - st_gt) <= window for ep, st in retrieved)


def _grade_chunk_recall(item: dict, retrieved: list[tuple[str, float]]) -> dict | None:
    scope = item
    if item.get("is_multi_turn"):
        turns = item.get("turns") or []
        scope = turns[0] if turns else item
    must = scope.get("ground_truth_chunk_ids_must") or []
    either = scope.get("ground_truth_chunk_ids_either") or []
    if not must and not either:
        return None
    must_hits = sum(1 for c in must if _chunk_in_retrieved(c, retrieved, _DEFAULT_WINDOW_S))
    either_hit = any(_chunk_in_retrieved(c, retrieved, _DEFAULT_WINDOW_S) for c in either)
    denominator = len(must) + (1 if either else 0)
    numerator = must_hits + (1 if either_hit else 0)
    score = min(numerator / denominator, 1.0) if denominator else 0.0
    return {
        "score": score,
        "must_hits": must_hits,
        "must_total": len(must),
        "either_group_hit": either_hit,
    }


DEFAULT_SHOW_ID = "45fc2462-17cf-42f5-98a7-68fe1a222228"
DEFAULT_MINI_SET = ["b20", "b21", "b23", "b15", "b16", "b17", "b19"]
CROSS_EPISODE_IDS = {"b20", "b21", "b23"}
DEEP_DIVE_IDS = {"b15", "b16", "b17", "b19"}

DATASET_PATH = Path(__file__).resolve().parents[3] / "eval" / "datasets" / "extended-multi-turn-40.json"


class RRFWeightTuple(BaseModel):
    chunk: float = Field(gt=0)
    description: float = Field(gt=0)
    title: float = Field(gt=0)


class RRFSweepRequest(BaseModel):
    candidates: list[RRFWeightTuple]
    show_id: str = DEFAULT_SHOW_ID
    mini_set_ids: list[str] = Field(default_factory=lambda: list(DEFAULT_MINI_SET))


router = APIRouter(prefix="/rrf", tags=["admin-rrf-sweep"])


def _load_items_indexed() -> dict[str, dict]:
    if not DATASET_PATH.exists():
        raise HTTPException(status_code=500, detail=f"dataset not found at {DATASET_PATH}")
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return {i["id"]: i for i in data.get("items", [])}


async def _embed(db: AsyncSession, question: str) -> list[float]:
    step = await get_step_config(db, "embedding")
    return embed_texts([question], step)[0]


async def _retrieve_and_grade(
    db: AsyncSession, show_id: uuid.UUID, item: dict
) -> dict[str, Any]:
    turn = item if not item.get("is_multi_turn") else (item.get("turns") or [item])[0]
    question = turn.get("question") or item.get("question")
    if not question:
        return {"item_id": item["id"], "score": None, "error": "no question"}

    epid_filter = None
    if not item.get("is_multi_turn"):
        eps = item.get("expected_episode_uuids_must") or []
        if eps and item.get("design_type") == "deep_dive":
            epid_filter = [uuid.UUID(eps[0])]

    vec = await _embed(db, question)
    hits = await rag.retrieve_hybrid(
        db,
        show_id=show_id,
        query_embedding=vec,
        question=question,
        k=5,
        episode_id_filter=epid_filter,
    )
    retrieved = [(str(h.episode_id), float(h.start_time)) for h in hits]
    graded = _grade_chunk_recall(item, retrieved)
    if graded is None:
        return {"item_id": item["id"], "score": None, "error": "no chunk GT"}
    return {"item_id": item["id"], **graded}


def _means(per_item: list[dict]) -> dict[str, Any]:
    def _avg(ids: set[str]) -> tuple[float | None, int]:
        scores = [r["score"] for r in per_item if r["item_id"] in ids and r.get("score") is not None]
        return (sum(scores) / len(scores) if scores else None, len(scores))

    ce_mean, ce_n = _avg(CROSS_EPISODE_IDS)
    dd_mean, dd_n = _avg(DEEP_DIVE_IDS)
    return {
        "cross_episode_recall_mean": ce_mean,
        "cross_episode_n": ce_n,
        "deep_dive_recall_mean": dd_mean,
        "deep_dive_n": dd_n,
    }


@router.post("/sweep")
async def rrf_sweep(req: RRFSweepRequest, db: AsyncSession = Depends(get_db)) -> dict:
    items_by_id = _load_items_indexed()
    show_id = uuid.UUID(req.show_id)

    # Track baseline index — the candidate with description == 0.7 (and chunk=1.0, title=0.5)
    baseline_index = next(
        (i for i, c in enumerate(req.candidates) if c.description == 0.7),
        None,
    )

    results: list[dict[str, Any]] = []
    original = dict(rag.RRF_WEIGHTS)
    try:
        for c in req.candidates:
            rag.RRF_WEIGHTS.update({"chunk": c.chunk, "description": c.description, "title": c.title})
            per_item: list[dict] = []
            for item_id in req.mini_set_ids:
                item = items_by_id.get(item_id)
                if item is None:
                    per_item.append({"item_id": item_id, "score": None, "error": "not in dataset"})
                    continue
                r = await _retrieve_and_grade(db, show_id, item)
                per_item.append(r)
            results.append({
                "weights": {"chunk": c.chunk, "description": c.description, "title": c.title},
                "per_item": per_item,
                **_means(per_item),
            })
    finally:
        rag.RRF_WEIGHTS.clear()
        rag.RRF_WEIGHTS.update(original)

    return {
        "baseline_index": baseline_index,
        "candidates": results,
    }
