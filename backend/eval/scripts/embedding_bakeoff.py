"""Embedding model bake-off — small-sample sentinel cosine comparison.

Goal:
    Compare `text-embedding-3-small` (current prod) vs a candidate model
    (default: `text-embedding-3-large`) on 10 sentinel items from
    `this-not-that-cool.json`. For each sentinel, embed the query and ALL
    candidate chunks (transcript + description) belonging to the source
    episode with BOTH models. Compute cosine similarity, report rank of
    GT-time-proximate chunks and episode-level recall@K.

Safety:
    - DRY-RUN by default: prints token estimate + cost projection, NO API calls.
    - --execute: actually call OpenAI Embeddings API for both models.
    - DOES NOT touch prod DB. Reads pre-staged JSON dumps from
      `docs/research/bakeoff-data/` produced by MCP read-only queries.
    - DOES NOT write to DB. Outputs results to a markdown file under
      `docs/research/`.

Usage:
    cd backend && python -m eval.scripts.embedding_bakeoff --dry-run
    cd backend && python -m eval.scripts.embedding_bakeoff --execute

Key resolution:
    Uses `app.services.key_resolver.get_provider_key('openai',
    prefer_env='OPENAI_OFFICIAL_KEY')`. The key comes from the DB
    `api_keys WHERE provider='openai'` row (single source of truth), or — for
    ad-hoc dev override — the `OPENAI_OFFICIAL_KEY` env var. The legacy
    `OPENAI_API_KEY` env var is intentionally NOT consulted: that variable
    holds the Zeabur AI Hub gateway key which does not support embeddings.

Cost ceiling (hard-enforced):
    If estimated cost > $0.20, refuse to run --execute and require
    --force-budget to override.

Output:
    `docs/research/embedding-bake-off-results-2026-05-12.md` with cosine
    similarities, ranks, episode-level recall, and conclusion section.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:
    print("ERROR: numpy not installed. pip install numpy", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = REPO_ROOT / "backend/eval/datasets/this-not-that-cool.json"
TRANSCRIPT_JSON = REPO_ROOT / "docs/research/bakeoff-data/transcript_chunks.json"
DESCRIPTION_JSON = REPO_ROOT / "docs/research/bakeoff-data/description_chunks.json"
OUTPUT_MD = REPO_ROOT / "docs/research/embedding-bake-off-results-2026-05-12.md"

# Pricing (USD per 1M tokens) — OpenAI as of 2026-05.
PRICING = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}

COST_CEILING_USD = 0.20


@dataclass
class Chunk:
    id: str
    source: str  # "transcript" | "description"
    episode_id: str
    text: str
    start_time: float = 0.0


def load_sentinels() -> list[dict]:
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return [it for it in data["items"] if it.get("sentinel")]


def load_chunks() -> list[Chunk]:
    out: list[Chunk] = []
    tc = json.loads(TRANSCRIPT_JSON.read_text(encoding="utf-8"))
    for r in tc:
        out.append(
            Chunk(
                id=r["id"],
                source=r["source"],
                episode_id=r["episode_id"],
                text=r["text"],
                start_time=float(r.get("start_time", 0.0)),
            )
        )
    dc = json.loads(DESCRIPTION_JSON.read_text(encoding="utf-8"))
    for r in dc:
        out.append(
            Chunk(
                id=r["id"],
                source=r["source"],
                episode_id=r["episode_id"],
                text=r["text"],
                start_time=float(r.get("start_time", 0.0)),
            )
        )
    return out


def estimate_tokens(texts: list[str]) -> int:
    """Heuristic token count without requiring tiktoken at top-level.
    For Chinese text, ~1 char ≈ 1.5 tokens (cl100k_base).
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return sum(len(enc.encode(t)) for t in texts)
    except ImportError:
        # Fallback: rough char-based approx (errs high → safe for budget)
        return int(sum(len(t) for t in texts) * 1.5)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def parse_gt_chunk_ids(item: dict) -> list[tuple[str, float]]:
    """Parse `ep:<uuid>@<start_time>` strings into (episode_id, start_time)."""
    out = []
    for s in item.get("ground_truth_chunk_ids", []):
        if not s.startswith("ep:"):
            continue
        body = s[len("ep:") :]
        if "@" not in body:
            continue
        ep, st = body.rsplit("@", 1)
        try:
            out.append((ep, float(st)))
        except ValueError:
            continue
    return out


def find_gt_proximate_chunks(
    item: dict, chunks: list[Chunk], window_sec: float = 60.0
) -> set[str]:
    """For each GT (episode_id, start_time), find the chunk whose start_time
    is within `window_sec` seconds. These are the bake-off's "GT chunks"
    given that re-chunking has shifted timestamps.
    """
    targets = parse_gt_chunk_ids(item)
    matched: set[str] = set()
    for ep, st in targets:
        cands = [
            c for c in chunks if c.source == "transcript" and c.episode_id == ep
        ]
        if not cands:
            continue
        nearest = min(cands, key=lambda c: abs(c.start_time - st))
        if abs(nearest.start_time - st) <= window_sec:
            matched.add(nearest.id)
    return matched


def embed_batch(client, model: str, texts: list[str]) -> np.ndarray:
    """Call OpenAI embeddings API in batches (max 2048 per call)."""
    BATCH = 256
    vecs: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        chunk = texts[i : i + BATCH]
        resp = client.embeddings.create(model=model, input=chunk)
        for d in resp.data:
            vecs.append(d.embedding)
    return np.array(vecs, dtype=np.float32)


def run_bakeoff(
    sentinels: list[dict],
    chunks: list[Chunk],
    models: list[str],
    api_key: str,
    top_k: int = 5,
) -> dict:
    from openai import OpenAI

    base_url = os.environ.get("OPENAI_BASE_URL") or None
    client = OpenAI(api_key=api_key, base_url=base_url)
    if base_url:
        print(f"  using base_url={base_url}", file=sys.stderr)

    # Index chunks by episode
    chunks_by_ep: dict[str, list[Chunk]] = {}
    for c in chunks:
        chunks_by_ep.setdefault(c.episode_id, []).append(c)

    # Embed all chunks per model — cache by (model, chunk_id) to avoid dups
    print("[1/3] Embedding all candidate chunks ...", file=sys.stderr)
    chunk_vecs: dict[str, dict[str, np.ndarray]] = {m: {} for m in models}
    for m in models:
        texts = [c.text for c in chunks]
        t0 = time.time()
        vecs = embed_batch(client, m, texts)
        dt = time.time() - t0
        print(
            f"  model={m} chunks={len(texts)} dim={vecs.shape[1]} took={dt:.1f}s",
            file=sys.stderr,
        )
        for c, v in zip(chunks, vecs):
            chunk_vecs[m][c.id] = v

    # Embed each query
    print("[2/3] Embedding queries ...", file=sys.stderr)
    query_vecs: dict[str, dict[str, np.ndarray]] = {m: {} for m in models}
    for m in models:
        qtexts = [s["question"] for s in sentinels]
        vecs = embed_batch(client, m, qtexts)
        for s, v in zip(sentinels, vecs):
            query_vecs[m][s["id"]] = v

    # Compute ranks
    print("[3/3] Scoring ...", file=sys.stderr)
    per_item: list[dict] = []
    for s in sentinels:
        ep = s.get("source_episode_id")
        if not ep or ep not in chunks_by_ep:
            continue
        cands = chunks_by_ep[ep]
        gt_ids = find_gt_proximate_chunks(s, cands, window_sec=60.0)
        item_result = {
            "id": s["id"],
            "question": s["question"],
            "source_episode_id": ep,
            "candidate_chunks": len(cands),
            "gt_chunk_count": len(gt_ids),
            "gt_chunk_ids": sorted(gt_ids),
            "is_negative": len(s.get("ground_truth_chunk_ids", [])) == 0,
            "models": {},
        }
        for m in models:
            qv = query_vecs[m][s["id"]]
            scored = []
            for c in cands:
                cv = chunk_vecs[m][c.id]
                scored.append((c.id, c.source, cosine(qv, cv)))
            scored.sort(key=lambda x: -x[2])
            top_ids = [t[0] for t in scored[:top_k]]
            ranks_of_gt: list[int] = []
            for gid in gt_ids:
                rank = next(
                    (i + 1 for i, t in enumerate(scored) if t[0] == gid), -1
                )
                if rank > 0:
                    ranks_of_gt.append(rank)
            hits = [t for t in scored[:top_k] if t[0] in gt_ids]
            item_result["models"][m] = {
                "top_k_ids": top_ids,
                "top_k_scores": [t[2] for t in scored[:top_k]],
                "top_k_sources": [t[1] for t in scored[:top_k]],
                "hits_in_topk": len(hits),
                "recall_at_k": len(hits) / max(1, len(gt_ids)),
                "best_gt_rank": min(ranks_of_gt) if ranks_of_gt else -1,
                "mean_gt_rank": (
                    sum(ranks_of_gt) / len(ranks_of_gt) if ranks_of_gt else -1
                ),
                "reciprocal_rank": (
                    1.0 / min(ranks_of_gt) if ranks_of_gt else 0.0
                ),
            }
        per_item.append(item_result)

    # Aggregate
    aggregate: dict[str, dict[str, float]] = {}
    for m in models:
        evaluable = [
            it for it in per_item if not it["is_negative"] and it["gt_chunk_count"] > 0
        ]
        if not evaluable:
            continue
        aggregate[m] = {
            "n": len(evaluable),
            "mean_recall_at_k": sum(
                it["models"][m]["recall_at_k"] for it in evaluable
            )
            / len(evaluable),
            "mean_reciprocal_rank": sum(
                it["models"][m]["reciprocal_rank"] for it in evaluable
            )
            / len(evaluable),
            "any_hit_at_k": sum(
                1 for it in evaluable if it["models"][m]["hits_in_topk"] > 0
            )
            / len(evaluable),
        }
    return {"per_item": per_item, "aggregate": aggregate, "top_k": top_k}


def render_markdown(results: dict, models: list[str], cost_actual: float) -> str:
    lines: list[str] = []
    lines.append("# Embedding Bake-off — Sentinel Cosine Results\n")
    lines.append("- 日期：2026-05-12")
    lines.append("- Pipeline：local cosine bake-off（不打 prod /search、不動 prod DB）")
    lines.append(f"- 比較 model：{', '.join(models)}")
    lines.append(f"- Top-K：{results['top_k']}")
    lines.append(f"- 實際 OpenAI cost：${cost_actual:.4f}")
    lines.append("- GT 對齊策略：用 dataset 原 GT 時間戳 ± 60 秒最近的 chunk 當 GT（因 R3.2 re-chunk 後時間戳已變動）")
    lines.append("")
    lines.append("## 聚合指標\n")
    lines.append("| Model | N 可評估 | mean Recall@K | mean Reciprocal Rank | Any-hit@K |")
    lines.append("|---|---|---|---|---|")
    for m, ag in results["aggregate"].items():
        lines.append(
            f"| `{m}` | {ag['n']} | {ag['mean_recall_at_k']:.3f} | {ag['mean_reciprocal_rank']:.3f} | {ag['any_hit_at_k']:.3f} |"
        )
    lines.append("")
    lines.append("## 每題詳細\n")
    for it in results["per_item"]:
        lines.append(f"### {it['id']} — {it['question']}\n")
        lines.append(
            f"- 來源 episode：`{it['source_episode_id'][:8]}` candidate chunks={it['candidate_chunks']} GT chunks={it['gt_chunk_count']}"
        )
        if it["is_negative"]:
            lines.append("- **negative item**（GT 為空，無 Recall 可算；觀察 top-1 是否亂喊）")
        for m in models:
            r = it["models"][m]
            lines.append(
                f"- `{m}`：Recall@K={r['recall_at_k']:.2f} best_rank={r['best_gt_rank']} RR={r['reciprocal_rank']:.3f}"
            )
            top1_score = r["top_k_scores"][0] if r["top_k_scores"] else 0
            lines.append(
                f"  - top-1 score={top1_score:.4f} source={r['top_k_sources'][0] if r['top_k_sources'] else 'n/a'}"
            )
        lines.append("")

    # Verdict
    if len(models) >= 2:
        m0, m1 = models[0], models[1]
        a0 = results["aggregate"].get(m0, {})
        a1 = results["aggregate"].get(m1, {})
        if a0 and a1:
            delta = a1.get("mean_recall_at_k", 0) - a0.get("mean_recall_at_k", 0)
            rr_delta = a1.get("mean_reciprocal_rank", 0) - a0.get(
                "mean_reciprocal_rank", 0
            )
            lines.append("## 結論\n")
            verdict = (
                "**候選 model 顯著優於 baseline**" if delta > 0.05 else
                "**候選 model 邊際優於 baseline**" if delta > 0.01 else
                "**候選 model 與 baseline 無顯著差異**" if abs(delta) <= 0.01 else
                "**候選 model 反而 worse than baseline**"
            )
            lines.append(verdict)
            lines.append("")
            lines.append(
                f"- mean Recall@K delta ({m1} - {m0}) = **{delta:+.3f}**"
            )
            lines.append(f"- mean Reciprocal Rank delta = **{rr_delta:+.3f}**")
            lines.append("")
            lines.append("### 建議 R3.4 proposal 採用方向")
            if delta > 0.05:
                lines.append(
                    f"- 推薦 swap 到 `{m1}`，預期 prod Recall@5 也會有對應幅度的拉升"
                )
                lines.append(
                    f"- ship 標準建議：Recall@5 ≥ 0.35（對齊 R3.2 原 gate）"
                )
            elif delta > 0.01:
                lines.append(
                    f"- `{m1}` 有邊際改善，但建議**先確認非 embedding-side 真兇**（chunking / RRF / lexical filter）已盡力過再 swap"
                )
                lines.append(
                    f"- 若仍要 swap，ship 標準建議：Recall@5 ≥ 0.30（軟 gate）"
                )
            else:
                lines.append(
                    "- 強烈不建議純 swap embedding model；R3.2 ceiling **不是 embedding 問題**，應該朝 chunking 細切 / RRF 融合 / bge-m3 hybrid 三路 retrieval 方向"
                )
                lines.append(
                    "- 本 change 可改為 narrative：**已驗證 OpenAI 同家上一階模型無實質幫助；建議下一輪走 bge-m3 open-source 路線**"
                )

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Default: estimate only, no API call.",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Actually call OpenAI embeddings API.",
    )
    p.add_argument(
        "--force-budget",
        action="store_true",
        help="Bypass $0.20 cost ceiling.",
    )
    p.add_argument(
        "--candidate",
        default="text-embedding-3-large",
        help="Candidate model name (must be OpenAI-compatible).",
    )
    p.add_argument("--top-k", type=int, default=5)
    args = p.parse_args()

    if args.execute:
        args.dry_run = False

    sentinels = load_sentinels()
    chunks = load_chunks()
    print(
        f"sentinels={len(sentinels)} candidate_chunks={len(chunks)} "
        f"(transcript={sum(1 for c in chunks if c.source=='transcript')}, "
        f"description={sum(1 for c in chunks if c.source=='description')})",
        file=sys.stderr,
    )

    models = ["text-embedding-3-small", args.candidate]
    all_text = [c.text for c in chunks] + [s["question"] for s in sentinels]
    tokens = estimate_tokens(all_text)
    # Each model embeds the same texts.
    total_cost = 0.0
    cost_per_model = {}
    for m in models:
        rate = PRICING.get(m)
        if rate is None:
            print(
                f"WARNING: no pricing entry for {m}; assuming $0.13/M",
                file=sys.stderr,
            )
            rate = 0.13
        c = tokens / 1_000_000 * rate
        cost_per_model[m] = c
        total_cost += c

    print(f"\n=== Cost Estimate ===", file=sys.stderr)
    print(f"  approx tokens (one model) = {tokens:,}", file=sys.stderr)
    for m, c in cost_per_model.items():
        print(f"  {m}: ${c:.4f}", file=sys.stderr)
    print(f"  TOTAL: ${total_cost:.4f}", file=sys.stderr)
    print("", file=sys.stderr)

    if args.dry_run:
        print("DRY-RUN complete. Pass --execute to actually run.", file=sys.stderr)
        return 0

    if total_cost > COST_CEILING_USD and not args.force_budget:
        print(
            f"REFUSING: cost ${total_cost:.4f} > ceiling ${COST_CEILING_USD}. "
            "Pass --force-budget to override.",
            file=sys.stderr,
        )
        return 3

    # Resolve key via the central provider-key-resolver. Order:
    #   1. OPENAI_OFFICIAL_KEY env var (ad-hoc dev override; distinct from
    #      OPENAI_API_KEY which holds the AI Hub gateway key and CANNOT call
    #      embeddings).
    #   2. DB api_keys table (provider='openai', most-recent row) — the single
    #      source of truth that the in-request backend also uses.
    # We no longer fall back to reading backend/.env directly, because that
    # path always hit the AI Hub key and produced confusing 401s.
    try:
        from app.services.key_resolver import get_provider_key
    except ImportError:
        print(
            "ERROR: cannot import app.services.key_resolver. "
            "Run from backend/ with PYTHONPATH=. (or inside the backend container).",
            file=sys.stderr,
        )
        return 4
    try:
        api_key = get_provider_key("openai", prefer_env="OPENAI_OFFICIAL_KEY")
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    results = run_bakeoff(sentinels, chunks, models, api_key=api_key, top_k=args.top_k)
    md = render_markdown(results, models, cost_actual=total_cost)
    OUTPUT_MD.write_text(md, encoding="utf-8")
    # Also drop raw JSON next to the md
    raw_path = OUTPUT_MD.with_suffix(".raw.json")
    raw_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_MD}", file=sys.stderr)
    print(f"Wrote {raw_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
