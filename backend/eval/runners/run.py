"""Main RAG eval runner — query backend retrieval/answer APIs against a golden set.

For each item:
  1. POST /shows/{show_id}/search to get top-K chunks (Recall@K, MRR).
  2. Optionally POST /shows/{show_id}/query to get the LLM-generated answer
     (judge score). Skipped if --skip-judge or auth missing.
  3. Aggregate per-type + overall metrics.

Output: JSON report + markdown summary in --out-dir.

Usage:
    python -m backend.eval.runners.run \\
        --dataset backend/eval/datasets/this-not-that-cool.json \\
        --backend-url https://api.podcastrag.app \\
        --auth-token "$EVAL_AUTH_TOKEN" \\
        --top-k 5 \\
        --out-dir backend/eval/results

Notes:
  - --auth-token is the e2e-login session cookie value (memory: e2e-login-backdoor).
    Required because /shows/.../search is rate-limited 20/day for anon callers.
  - Negative items (empty ground_truth) are excluded from Recall/MRR averages
    but still scored by the judge (answer should say "not mentioned").
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable

try:
    # Invoked as `python -m backend.eval.runners.run` from repo root
    from backend.eval.metrics.mrr import reciprocal_rank
    from backend.eval.metrics.recall import recall_at_k
except ModuleNotFoundError:
    # Invoked under pytest with cwd=backend/
    from eval.metrics.mrr import reciprocal_rank
    from eval.metrics.recall import recall_at_k


# Lenient chunk match: production retrieval returns chunk-level start_times
# (multiple segments aggregated; high-precision floats), while the golden set
# anchors at segment-level (clean 2-decimal). Bucket both to a window so a
# retrieved chunk that *contains* an anchor segment counts as a hit.
DEFAULT_MATCH_WINDOW_S = 10.0


def _bucket(chunk_id: str, window_s: float) -> tuple[str, int]:
    """Convert `ep:<uuid>@<seconds>` to (uuid, floor(seconds/window))."""
    try:
        head, tail = chunk_id.split("@", 1)
        ep_id = head.removeprefix("ep:")
        return (ep_id, int(float(tail) // window_s))
    except (ValueError, IndexError):
        return ("", -1)


def _to_lenient_ids(chunk_ids: list[str], window_s: float) -> list[str]:
    """Re-encode each chunk_id as `ep:<uuid>@<bucket>` for set-equality match."""
    return [f"ep:{ep}@{bucket}" for ep, bucket in (_bucket(c, window_s) for c in chunk_ids) if ep]

REPO_ROOT = Path(__file__).resolve().parents[3]


# ────────────────────────────────────────────────────────────────────
# HTTP helpers
# ────────────────────────────────────────────────────────────────────

def _post(url: str, body: dict, token: str, timeout: float = 60.0) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Cookie"] = f"session_id={token}"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _to_chunk_id(hit: dict) -> str:
    return f"ep:{hit['episode_id']}@{float(hit['start_time']):.2f}"


def _retrieve(
    backend_url: str, show_id: str, question: str, k: int, token: str,
) -> tuple[list[str], list[str], float]:
    """Return (chunk_ids, chunk_texts, latency_ms). Empty lists on failure."""
    t0 = time.monotonic()
    try:
        resp = _post(
            f"{backend_url}/shows/{show_id}/search",
            {"question": question, "k": k},
            token,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[warn] retrieve failed: {exc}", file=sys.stderr)
        return [], [], 0.0
    latency_ms = (time.monotonic() - t0) * 1000
    hits = resp.get("results", [])
    return [_to_chunk_id(h) for h in hits], [h.get("text", "") for h in hits], latency_ms


def _query(
    backend_url: str, show_id: str, question: str, token: str,
) -> tuple[str, list[str]]:
    """Return (answer_text, retrieval_context_texts). Empty on failure."""
    try:
        resp = _post(
            f"{backend_url}/shows/{show_id}/query",
            {"question": question},
            token,
        )
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[warn] query failed: {exc}", file=sys.stderr)
        return "", []
    answer = resp.get("answer") or resp.get("response") or ""
    sources = resp.get("sources") or resp.get("results") or []
    context = [s.get("text", "") for s in sources if s.get("text")]
    return answer, context


# ────────────────────────────────────────────────────────────────────
# Aggregation
# ────────────────────────────────────────────────────────────────────

def _aggregate(items: list[dict]) -> dict:
    """Compute overall + per-type means. Recall/RR exclude None; judge excludes None."""
    def _agg(group: list[dict]) -> dict:
        recalls = [it["recall_at_k"] for it in group if it["recall_at_k"] is not None]
        rrs = [it["reciprocal_rank"] for it in group if it["recall_at_k"] is not None]
        judges = [it["judge_score"] for it in group if it.get("judge_score") is not None]
        latencies = [it["latency_ms"] for it in group if it.get("latency_ms")]
        return {
            "n": len(group),
            "n_scored_retrieval": len(recalls),
            "recall_at_k_mean": round(mean(recalls), 4) if recalls else None,
            "mrr": round(mean(rrs), 4) if rrs else None,
            "judge_score_mean": round(mean(judges), 4) if judges else None,
            "latency_p95_ms": round(_p95(latencies), 1) if latencies else None,
        }

    by_type: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_type[it["type"]].append(it)
    return {
        "overall": _agg(items),
        "by_type": {t: _agg(g) for t, g in sorted(by_type.items())},
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(0.95 * (len(s) - 1))
    return s[idx]


# ────────────────────────────────────────────────────────────────────
# Markdown report
# ────────────────────────────────────────────────────────────────────

def _markdown_report(report: dict) -> str:
    m = report["metrics"]
    lines = [
        f"# RAG eval — {report['dataset']} ({report['version']})",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- backend: `{report['backend']}`",
        f"- judge_model: `{report.get('judge_model') or '(skipped)'}`",
        f"- top_k: {report['top_k']}",
        f"- n_items: {report['n_items']}",
        "",
        "## Overall",
        "",
        "| metric | value |",
        "|---|---|",
        f"| Recall@{report['top_k']} ({report.get('metric_level','chunk')}) | {m['overall']['recall_at_k_mean']} |",
        f"| MRR | {m['overall']['mrr']} |",
        f"| Judge mean (1-5) | {m['overall']['judge_score_mean']} |",
        f"| Latency P95 (ms) | {m['overall']['latency_p95_ms']} |",
        "",
        "## By type",
        "",
        "| type | n | Recall@K | MRR | Judge | P95 ms |",
        "|---|---|---|---|---|---|",
    ]
    for t, agg in m["by_type"].items():
        lines.append(
            f"| {t} | {agg['n']} | {agg['recall_at_k_mean']} | {agg['mrr']} | "
            f"{agg['judge_score_mean']} | {agg['latency_p95_ms']} |"
        )
    return "\n".join(lines) + "\n"


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def _to_episode_ids(chunk_ids: list[str]) -> list[str]:
    """Extract just the episode_id portion of `ep:<uuid>@<time>` strings."""
    out = []
    for cid in chunk_ids:
        head = cid.split("@", 1)[0]
        if head.startswith("ep:"):
            out.append(head[3:])
        elif head.startswith("desc:"):
            out.append(head[5:])
        else:
            out.append(head)
    return out


def run_eval(
    dataset_path: Path,
    backend_url: str,
    token: str,
    top_k: int,
    skip_judge: bool,
    out_dir: Path,
    match_window_s: float = DEFAULT_MATCH_WINDOW_S,
    metric_level: str = "episode",
) -> dict:
    """Execute eval; return report dict + write JSON/MD to out_dir."""
    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    show_id = data["show_id"]
    items = data["items"]

    judge_fn = None
    judge_model = None
    if not skip_judge:
        try:
            try:
                from backend.eval.judge_config import PRODUCTION_JUDGE_MODEL
                from backend.eval.metrics.judge_metrics import judge_score
            except ModuleNotFoundError:
                from eval.judge_config import PRODUCTION_JUDGE_MODEL
                from eval.metrics.judge_metrics import judge_score
            judge_fn = judge_score
            judge_model = PRODUCTION_JUDGE_MODEL
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] judge unavailable ({exc}); continuing retrieval-only", file=sys.stderr)

    out_items: list[dict] = []
    for i, item in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {item['id']} ({item['type']})…", file=sys.stderr)
        chunk_ids, chunk_texts, latency_ms = _retrieve(
            backend_url, show_id, item["question"], top_k, token,
        )
        gt = item.get("ground_truth_chunk_ids", [])
        if metric_level == "episode":
            # Episode-level match: hit if any retrieved chunk shares episode_id
            # with any anchor (ignores start_time and `match_window_s`).
            retrieved_match = _to_episode_ids(chunk_ids)
            gt_match = _to_episode_ids(gt)
        else:
            # Chunk-level (legacy R1.2 / R3.1 behaviour) — bucket by window.
            retrieved_match = _to_lenient_ids(chunk_ids, match_window_s)
            gt_match = _to_lenient_ids(gt, match_window_s)
        rec = recall_at_k(retrieved_match, gt_match, k=top_k)
        rr = reciprocal_rank(retrieved_match, gt_match) if gt_match else None

        judge_val: float | None = None
        if judge_fn is not None:
            answer, ctx_texts = _query(backend_url, show_id, item["question"], token)
            if answer:
                # Use the actual /query retrieved context if available, else fall back to /search chunks.
                ctx = ctx_texts or chunk_texts
                try:
                    judge_val = judge_fn(item["question"], answer, ctx)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [warn] judge failed: {exc}", file=sys.stderr)

        out_items.append({
            "id": item["id"],
            "type": item["type"],
            "question": item["question"],
            "recall_at_k": rec,
            "reciprocal_rank": rr,
            "judge_score": judge_val,
            "latency_ms": round(latency_ms, 1),
            "retrieved_chunk_ids": chunk_ids,
        })

    metrics = _aggregate(out_items)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "dataset": data["show_slug"],
        "version": data["version"],
        "run_id": run_id,
        "backend": backend_url,
        "judge_model": judge_model,
        "top_k": top_k,
        "metric_level": metric_level,
        "n_items": len(items),
        "metrics": metrics,
        "items": out_items,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"eval-{data['show_slug']}-{run_id}.json"
    md_path = out_dir / f"eval-{data['show_slug']}-{run_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    print(f"\n[ok] report: {json_path}", file=sys.stderr)
    print(f"[ok] summary: {md_path}", file=sys.stderr)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RAG eval against a backend")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument(
        "--auth-token",
        default=os.environ.get("EVAL_AUTH_TOKEN", ""),
        help="Session cookie value (or env EVAL_AUTH_TOKEN). Optional but recommended.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--match-window-s",
        type=float,
        default=DEFAULT_MATCH_WINDOW_S,
        help="Seconds. A retrieved chunk counts as a hit if its start_time is within "
        "this window of an anchor's start_time (same episode). Default 10s.",
    )
    parser.add_argument(
        "--metric-level",
        choices=["episode", "chunk"],
        default="episode",
        help="`episode`: hit if retrieved chunk's episode_id matches any anchor "
        "episode_id (R3.2 default, fair to description hits). `chunk`: legacy "
        "R1.2/R3.1 behaviour using start_time bucketing.",
    )
    parser.add_argument("--skip-judge", action="store_true", help="Retrieval metrics only")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "backend/eval/results",
    )
    args = parser.parse_args(argv)

    if not args.dataset.exists():
        print(f"dataset not found: {args.dataset}", file=sys.stderr)
        return 2

    run_eval(
        dataset_path=args.dataset,
        backend_url=args.backend_url.rstrip("/"),
        token=args.auth_token,
        top_k=args.top_k,
        skip_judge=args.skip_judge,
        out_dir=args.out_dir,
        match_window_s=args.match_window_s,
        metric_level=args.metric_level,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
