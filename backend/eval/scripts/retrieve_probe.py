"""Episode-scoped retrieval probe.

PR-time CLI for episode-scoped retrieval verification — answers the question
"for query Q on episode E, what does retrieve_hybrid return in top-K and does
it include the GT chunks?"

Background: 2026-05-28 step1-idf-and-prefilter shipped & failed because the
show-wide DB probe (`POST /admin/diagnose/prefilter-rank`) was a false-positive
validator — it confirmed IDF-bucketed weighting beat baseline on show-wide
ranking, but the chat agent's episode-scoped retrieve_hybrid(episode_id_filter=...)
actually regressed (chunk_recall 0.482 → 0.382). This probe closes that gap.

Usage (local docker DB):
    python -m backend.eval.scripts.retrieve_probe \\
        --show-id 45fc2462-17cf-42f5-98a7-68fe1a222228 \\
        --episode-id 65030207-726d-43ba-80d4-d4c0efb97ac8 \\
        --query "伴手禮 現吃好吃 食物" \\
        --top-k 20 \\
        --dataset backend/eval/datasets/_calibration_8.json \\
        --item-id b18

For prod DB (the only place with real podcast data), override DATABASE_URL
or run via `zeabur service exec --id <backend-svc-id> -- python -m
backend.eval.scripts.retrieve_probe ...` from inside the backend container.

The `--dataset` + `--item-id` pair is optional. If provided, GT chunks are
loaded from the dataset item's `ground_truth_chunk_ids_must` /
`ground_truth_chunk_ids_either` / `ground_truth_chunk_ids_acceptable` and the
output flags any rank that hits a GT chunk with a `← GT` marker.

GT chunk id format: `ep:<episode_uuid>@<start_time>` (matches grader convention).

Exit 0 always — this is an observability tool, not a gate.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / "backend" / ".env")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services import rag  # noqa: E402
from app.services.ai_step_resolver import get_step_config  # noqa: E402
from app.services.embedding import embed_texts  # noqa: E402


def _format_gt_id(episode_uuid: str, start_time: float) -> str:
    return f"ep:{episode_uuid}@{start_time}"


def _load_gt_chunks(dataset_path: Path | None, item_id: str | None) -> set[str]:
    if not dataset_path or not item_id:
        return set()
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    items = dataset.get("items") or []
    matched = next((it for it in items if it.get("id") == item_id), None)
    if matched is None:
        print(f"[warn] item_id {item_id!r} not found in dataset", file=sys.stderr)
        return set()
    scope = matched
    if matched.get("is_multi_turn"):
        turns = matched.get("turns") or []
        if turns:
            scope = turns[0]
    gt: set[str] = set()
    for key in (
        "ground_truth_chunk_ids_must",
        "ground_truth_chunk_ids_either",
        "ground_truth_chunk_ids_acceptable",
    ):
        for cid in scope.get(key) or []:
            gt.add(cid)
    return gt


async def _run(
    show_id: uuid.UUID,
    episode_id: uuid.UUID | None,
    query: str,
    top_k: int,
    gt_chunks: set[str],
) -> int:
    engine = create_async_engine(settings.DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        embed_cfg = await get_step_config(db, "embedding")
        vec = embed_texts([query], embed_cfg)[0]
        epid_filter = [episode_id] if episode_id else None
        hits = await rag.retrieve_hybrid(
            db,
            show_id=show_id,
            query_embedding=vec,
            question=query,
            k=top_k,
            episode_id_filter=epid_filter,
        )

    print()
    scope_label = f"episode={episode_id}" if episode_id else "show-wide"
    print(f"=== retrieve_hybrid probe ({scope_label}, k={top_k}) ===")
    print(f"query: {query}")
    if gt_chunks:
        print(f"GT chunks ({len(gt_chunks)}): {sorted(gt_chunks)}")
    print()
    print(f"{'rank':>4}  {'rrf':>8}  {'source':10}  {'start':>9}  {'chunk_id':38}  GT?")
    print("-" * 92)
    gt_hits = 0
    for i, h in enumerate(hits, 1):
        chunk_id_str = str(h.chunk_id) if h.chunk_id else "-"
        canonical = _format_gt_id(str(h.episode_id), float(h.start_time or 0.0))
        is_gt = canonical in gt_chunks
        if is_gt:
            gt_hits += 1
        marker = "← GT" if is_gt else ""
        print(
            f"{i:>4}  {h.rrf_score:>8.5f}  {h.source[:10]:10}  "
            f"{h.start_time or 0.0:>9.2f}  {chunk_id_str:38}  {marker}"
        )
    print()
    if gt_chunks:
        print(f"GT hits in top-{top_k}: {gt_hits}/{len(gt_chunks)}")
    print(f"total hits returned: {len(hits)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--show-id", required=True, help="Show UUID")
    ap.add_argument(
        "--episode-id",
        default=None,
        help="Episode UUID to scope retrieval; omit for show-wide",
    )
    ap.add_argument("--query", required=True, help="Search query string")
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument(
        "--dataset",
        default=None,
        help="Optional dataset JSON path for GT chunk lookup",
    )
    ap.add_argument(
        "--item-id",
        default=None,
        help="Dataset item id (e.g. b18); requires --dataset",
    )
    args = ap.parse_args()

    gt = _load_gt_chunks(
        Path(args.dataset) if args.dataset else None,
        args.item_id,
    )
    return asyncio.run(
        _run(
            show_id=uuid.UUID(args.show_id),
            episode_id=uuid.UUID(args.episode_id) if args.episode_id else None,
            query=args.query,
            top_k=args.top_k,
            gt_chunks=gt,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
