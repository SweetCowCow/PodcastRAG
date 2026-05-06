"""Judge model bake-off — score 4 candidates against a hand-scored mini-set.

For each candidate the script invokes DeepEval's GEval with a custom 1-5
trust+groundedness rubric (configured to call via Zeabur AI Hub) on each
mini-set item, then computes Spearman rank correlation against the human
1-5 score. (Original FaithfulnessMetric had too-coarse output — only
3-6 distinct values across 40 items — so we switched to GEval 2026-05-07.)

Output: a sorted result table printed to stdout with cost estimates. With
`--write-config`, the lowest-cost candidate passing Spearman ≥ 0.7 is
written into `backend/eval/judge_config.py:PRODUCTION_JUDGE_MODEL`.

Usage:
    python -m backend.eval.scripts.judge_bakeoff
    python -m backend.eval.scripts.judge_bakeoff --write-config
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import correlation
from typing import Iterable
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[3]
MINISSET_PATH = REPO_ROOT / "backend/eval/datasets/_judge_minisset.json"
CONFIG_PATH = REPO_ROOT / "backend/eval/judge_config.py"

CANDIDATES = [
    "gpt-5-nano",
    "gemini-2.5-flash-lite",
    "gpt-4o-mini",
    "claude-haiku-4-5",
]

SPEARMAN_THRESHOLD = 0.7


def _ranks(values: list[float]) -> list[float]:
    """Average-rank assignment (handles ties). 1-based ranks."""
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-based, average of tied positions
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation = Pearson on ranks. Stdlib only, py3.9+ compatible."""
    if len(xs) != len(ys) or len(xs) < 3:
        raise ValueError("need ≥3 paired observations")
    return correlation(_ranks(xs), _ranks(ys))


def _estimate_cost_usd(model: str, n_items: int) -> float:
    """Rough cost estimate. ~2K input + 0.5K output tokens per faithfulness call."""
    from backend.eval.judge_config import HUB_PRICING_USD_PER_1M
    p = HUB_PRICING_USD_PER_1M.get(model)
    if p is None:
        return float("nan")
    input_m = n_items * 2000 / 1_000_000
    output_m = n_items * 500 / 1_000_000
    return input_m * p["input"] + output_m * p["output"]


GEVAL_CRITERIA = """評估這個答案在給定 retrieval context 下的整體可信度與相關性，給 1-5 分。

- 5 分：答案完全基於 context，正確、完整、措辭得體；若 context 無相關資訊，答案應誠實承認
- 4 分：答案大致基於 context，正確但可能有小遺漏或措辭可改善
- 3 分：答案部分基於 context，遺漏明顯資訊、或回答只有一半正確
- 2 分：答案與 context 關聯薄弱，或包含 context 未支持的資訊（部分捏造）
- 1 分：答案與 context 不符、明顯捏造、誤導性、或答非所問

特別注意：
- 「context 沒提到」這種誠實回答，若 context 確實沒提到 → 5 分
- 若 context 其實有提到、但答案說「沒提到」→ 1-2 分
- 中英夾雜、口語化都不扣分，只看 grounding 與相關性
"""


def _score_one(model: str, item: dict) -> float:
    """Run GEval for a single item. Returns score 0..1 (DeepEval normalizes 1-5 → 0-1 internally)."""
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams
    os.environ["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY") or ""
    os.environ["OPENAI_BASE_URL"] = "https://hnd1.aihub.zeabur.ai/v1"
    metric = GEval(
        name="TrustGroundedness",
        criteria=GEVAL_CRITERIA,
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.RETRIEVAL_CONTEXT,
        ],
        model=model,
        async_mode=False,
        threshold=0.0,
    )
    case = LLMTestCase(
        input=item["question"],
        actual_output=item["answer"],
        retrieval_context=item["chunks"],
    )
    metric.measure(case)
    return float(metric.score)


def run_bakeoff(miniset_path: Path) -> list[dict]:
    """Run all candidates against the mini-set; return rows sorted by spearman desc."""
    with miniset_path.open(encoding="utf-8") as f:
        data = json.load(f)
    items = data["items"]
    human = [float(it["human_score"]) for it in items]

    results_dir = REPO_ROOT / "backend/eval/results"
    results_dir.mkdir(parents=True, exist_ok=True)
    raw_path = results_dir / f"bakeoff-raw-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    raw: dict = {"human": human, "candidates": {}}

    rows: list[dict] = []
    for model in CANDIDATES:
        judge: list[float] = []
        try:
            for it in items:
                s = _score_one(model, it)
                judge.append(s)
                raw["candidates"][model] = judge  # incremental save after each item
                raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            rho = _spearman(judge, human)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {model} failed: {exc}", file=sys.stderr)
            continue
        rows.append({
            "model": model,
            "spearman": round(rho, 3),
            "pass_threshold": rho >= SPEARMAN_THRESHOLD,
            "cost_usd": round(_estimate_cost_usd(model, len(items)), 4),
        })

    print(f"[info] raw judge scores written to {raw_path}", file=sys.stderr)
    rows.sort(key=lambda r: r["spearman"], reverse=True)
    return rows


def _print_table(rows: list[dict]) -> None:
    print(f"\n{'model':<28} {'spearman':>9} {'pass':>5} {'cost_usd':>10}")
    print("-" * 56)
    for r in rows:
        print(f"{r['model']:<28} {r['spearman']:>9.3f} {str(r['pass_threshold']):>5} {r['cost_usd']:>10.4f}")
    print()


def _select_winner(rows: list[dict]) -> dict | None:
    passing = [r for r in rows if r["pass_threshold"]]
    if not passing:
        return None
    passing.sort(key=lambda r: r["cost_usd"])
    return passing[0]


def _write_config(model: str) -> None:
    src = CONFIG_PATH.read_text(encoding="utf-8")
    new_src = []
    for line in src.splitlines(keepends=True):
        if line.startswith("PRODUCTION_JUDGE_MODEL"):
            new_src.append(f'PRODUCTION_JUDGE_MODEL = "{model}"\n')
        else:
            new_src.append(line)
    CONFIG_PATH.write_text("".join(new_src), encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Judge model bake-off")
    parser.add_argument(
        "--miniset", type=Path, default=MINISSET_PATH,
        help="Path to mini-set JSON (default: backend/eval/datasets/_judge_minisset.json)",
    )
    parser.add_argument(
        "--write-config", action="store_true",
        help="On success, overwrite PRODUCTION_JUDGE_MODEL in judge_config.py",
    )
    args = parser.parse_args(argv)

    if not args.miniset.exists():
        print(f"mini-set not found: {args.miniset}", file=sys.stderr)
        return 2

    rows = run_bakeoff(args.miniset)
    _print_table(rows)

    if args.write_config:
        winner = _select_winner(rows)
        if winner is None:
            print("No candidate passed Spearman ≥ 0.7 — config NOT modified.", file=sys.stderr)
            return 1
        _write_config(winner["model"])
        print(f"PRODUCTION_JUDGE_MODEL set to {winner['model']} "
              f"(spearman={winner['spearman']}, cost_usd={winner['cost_usd']:.4f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
