"""RRF weight sweep harness for retrieval-cross-episode-recall-improvement.

For each candidate weight tuple, monkey-patches `backend.app.services.rag.RRF_WEIGHTS`,
runs an in-process retrieval against the prod DB (read-only) for a focused mini-set of
items, and computes the chunk_recall_grouped score per item. Then aggregates two means
per the acceptance gate:

  - cross_episode_recall_mean: b20 / b21 / b23 (cross-episode hard items)
  - deep_dive_recall_mean: b15 / b16 / b17 / b19 (perfect-recall control set)

Outputs a markdown table to stdout and writes a JSON sweep result file.

Usage:
    python -m backend.eval.scripts.rrf_weight_sweep \\
        --dataset backend/eval/datasets/extended-multi-turn-40.json \\
        --output /tmp/rrf-sweep.json

Reads candidate weights from a default list inside this script (per spec task 2.1):
    description ∈ {0.7 baseline, 0.85, 1.0, 1.2, 1.5} + sanity {0.3, 2.0}.
chunk fixed at 1.0, title fixed at 0.5.

All DB queries are SELECTs only — sweep is read-only against prod.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

# Load backend/.env so DATABASE_URL + OPENAI_API_KEY are available
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / "backend" / ".env")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services import rag  # noqa: E402
from app.services.embedding import embed_texts  # noqa: E402
from app.services.ai_step_resolver import get_step_config  # noqa: E402
from backend.eval.graders.chunk_recall_grouped import grade as grade_recall  # noqa: E402

# Mini-set per spec (rag-eval-runner) acceptance gate definition
CROSS_EPISODE_IDS = ["b20", "b21", "b23"]
DEEP_DIVE_IDS = ["b15", "b16", "b17", "b19"]
MINI_SET_IDS = CROSS_EPISODE_IDS + DEEP_DIVE_IDS

DEFAULT_CANDIDATES = [
    {"chunk": 1.0, "description": 0.7, "title": 0.5},   # baseline
    {"chunk": 1.0, "description": 0.85, "title": 0.5},
    {"chunk": 1.0, "description": 1.0, "title": 0.5},
    {"chunk": 1.0, "description": 1.2, "title": 0.5},
    {"chunk": 1.0, "description": 1.5, "title": 0.5},
    {"chunk": 1.0, "description": 0.3, "title": 0.5},   # sanity: should hurt cross_ep
    {"chunk": 1.0, "description": 2.0, "title": 0.5},   # sanity: should hurt deep_dive
]


def _items_indexed(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in dataset.get("items", [])}


async def _embed_question(db, question: str) -> list[float]:
    step = await get_step_config(db, "embedding")
    return embed_texts([question], step)[0]


async def _run_one_item(
    db, show_id: uuid.UUID, item: dict[str, Any]
) -> dict[str, Any]:
    """Returns {'item_id', 'score', 'must_hits', 'must_total', 'either_group_hit'}."""
    # For multi-turn items the focused scoring scope is the first turn (per grader)
    turn = item if not item.get("is_multi_turn") else (item.get("turns") or [item])[0]
    question = turn.get("question") or item.get("question")
    if not question:
        return {"item_id": item["id"], "score": None, "error": "no question"}

    must = turn.get("ground_truth_chunk_ids_must") or []
    either = turn.get("ground_truth_chunk_ids_either") or []
    acceptable = turn.get("ground_truth_chunk_ids_acceptable") or []
    if not must and not either and not acceptable:
        return {"item_id": item["id"], "score": None, "error": "no chunk GT"}

    # Optional episode_id_filter — for cross-episode items keep None (let RRF
    # fuse across whole show), for deep-dive items pass the EP UUID like agent does.
    epid_filter = None
    if not item.get("is_multi_turn"):
        eps = item.get("expected_episode_uuids_must") or []
        if eps and item.get("design_type") == "deep_dive":
            epid_filter = [uuid.UUID(eps[0])]

    vec = await _embed_question(db, question)
    hits = await rag.retrieve_hybrid(
        db,
        show_id=show_id,
        query_embedding=vec,
        question=question,
        k=5,
        episode_id_filter=epid_filter,
    )

    # Build a faux agent_response.citations list so the grader can read it
    citations = [
        {"episode_id": str(h.episode_id), "start_time": float(h.start_time)}
        for h in hits
    ]
    result = grade_recall(item, {"citations": citations})
    if result is None:
        return {"item_id": item["id"], "score": None, "error": "grader returned None"}
    return {
        "item_id": item["id"],
        "score": result["score"],
        "must_hits": result["details"]["must_hits"],
        "must_total": result["details"]["must_total"],
        "either_group_hit": result["details"]["either_group_hit"],
    }


async def _sweep_candidate(
    db, show_id: uuid.UUID, items_by_id: dict, weights: dict[str, float]
) -> dict[str, Any]:
    """Patch RRF_WEIGHTS for this candidate, run all mini-set items, return summary."""
    original = dict(rag.RRF_WEIGHTS)
    rag.RRF_WEIGHTS.update(weights)
    try:
        per_item: list[dict[str, Any]] = []
        for item_id in MINI_SET_IDS:
            item = items_by_id.get(item_id)
            if item is None:
                continue
            r = await _run_one_item(db, show_id, item)
            per_item.append(r)
    finally:
        # restore so subsequent candidates start clean
        rag.RRF_WEIGHTS.clear()
        rag.RRF_WEIGHTS.update(original)

    def _mean(ids: list[str]) -> tuple[float | None, int]:
        scores = [
            r["score"] for r in per_item
            if r["item_id"] in ids and r.get("score") is not None
        ]
        return (sum(scores) / len(scores) if scores else None, len(scores))

    ce_mean, ce_n = _mean(CROSS_EPISODE_IDS)
    dd_mean, dd_n = _mean(DEEP_DIVE_IDS)
    return {
        "weights": weights,
        "per_item": per_item,
        "cross_episode_recall_mean": ce_mean,
        "cross_episode_n": ce_n,
        "deep_dive_recall_mean": dd_mean,
        "deep_dive_n": dd_n,
    }


def _evaluate_gate(
    candidate: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    """Apply spec gate: cross_ep_mean strictly > baseline AND deep_dive does not
    drop by more than 0.05 absolute."""
    base_ce = baseline.get("cross_episode_recall_mean")
    base_dd = baseline.get("deep_dive_recall_mean")
    ce = candidate.get("cross_episode_recall_mean")
    dd = candidate.get("deep_dive_recall_mean")
    if ce is None or dd is None or base_ce is None or base_dd is None:
        return {"accepted": False, "reason": "missing means"}
    if not (ce > base_ce):
        return {"accepted": False, "reason": f"no cross_episode gain ({ce:.3f} <= {base_ce:.3f})"}
    if (base_dd - dd) > 0.05:
        return {"accepted": False, "reason": f"deep_dive regression {dd:.3f} below {base_dd - 0.05:.3f}"}
    return {"accepted": True, "reason": "passed both gates"}


async def _main_async(args: argparse.Namespace) -> int:
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    show_id = uuid.UUID(dataset["show_id"])
    items_by_id = _items_indexed(dataset)

    # Async DB session pointing at prod (DATABASE_URL from backend/.env)
    db_url = settings.database_url
    engine = create_async_engine(db_url, pool_pre_ping=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    candidates = (
        json.loads(args.weights) if args.weights else DEFAULT_CANDIDATES
    )

    results: list[dict[str, Any]] = []
    async with session_maker() as db:
        for i, w in enumerate(candidates, 1):
            label = f"description={w['description']}"
            print(f"[{i}/{len(candidates)}] sweeping {label}…", flush=True)
            r = await _sweep_candidate(db, show_id, items_by_id, w)
            print(
                f"  cross_episode_mean={r['cross_episode_recall_mean']:.3f} (n={r['cross_episode_n']})"
                f"  deep_dive_mean={r['deep_dive_recall_mean']:.3f} (n={r['deep_dive_n']})",
                flush=True,
            )
            results.append(r)
    await engine.dispose()

    # Mark baseline (first entry per default; or explicit description=0.7 match)
    baseline = next(
        (r for r in results if r["weights"].get("description") == 0.7),
        results[0],
    )
    for r in results:
        r["gate"] = _evaluate_gate(r, baseline)

    output = {
        "baseline_weights": baseline["weights"],
        "baseline_cross_episode_mean": baseline["cross_episode_recall_mean"],
        "baseline_deep_dive_mean": baseline["deep_dive_recall_mean"],
        "candidates": results,
    }
    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Render markdown summary
    print("\n## Sweep summary\n")
    print("| description | cross_ep_mean | deep_dive_mean | accepted? | reason |")
    print("|---:|---:|---:|---|---|")
    for r in results:
        desc_w = r["weights"]["description"]
        ce = r["cross_episode_recall_mean"]
        dd = r["deep_dive_recall_mean"]
        g = r["gate"]
        tag = "**baseline**" if r is baseline else ("✅" if g["accepted"] else "❌")
        print(
            f"| {desc_w} | {ce:.3f} | {dd:.3f} | {tag} | {g['reason']} |"
        )

    print(f"\n✓ wrote {args.output}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dataset",
        default="backend/eval/datasets/extended-multi-turn-40.json",
    )
    ap.add_argument(
        "--output",
        default="/tmp/rrf-sweep.json",
        help="path to write the sweep result JSON",
    )
    ap.add_argument(
        "--weights",
        default=None,
        help="optional JSON list of {chunk, description, title} dicts to override defaults",
    )
    args = ap.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
