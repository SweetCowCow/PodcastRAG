#!/usr/bin/env python3
"""Calibrate the PRODUCTION LLM-as-judge against the human-scored mini-set.

Change `r1-3-j-judge-harness-align`: this script previously measured a
stand-in judge (its own inline prompt + a hard-coded judge model), so its
Spearman said nothing about the judge that actually scores chat eval. It now drives
the production judge path — `backend/eval/judge_chat_v2.py` loading
`backend/eval/prompts/chat_judge_v2.md` — over an adapter that shapes each
static mini-set item into the judge payload, then reduces the judge's four
structured verdicts to ONE refusal-aware scalar rank-correlated against
`human_score`.

Refusal-aware reduction (numeric anchors, recorded per design):
- `expected_behavior` in {refuse, refusal_with_correction}:
      scalar = 1.0 if refusal_appropriateness.verdict == "appropriate" else 0.0
  (a faithful refusal the human rated 5 maps high — the exact case the old
  inline prompt scored 0 and broke the correlation)
- `expected_behavior` == "answer": scalar = factual_correctness.score
- judge error envelope on an item -> the item is dropped from the
  correlation (reported, not fatal).

Usage:
    python -m backend.scripts.llm_judge_calibration                  # production judge model
    python -m backend.scripts.llm_judge_calibration --model gpt-5.1  # sweep override

Env: AIHUB_API_KEY (or OPENAI_API_KEY pointing at the AI Hub endpoint).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import correlation
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.eval.judge_chat_v2 import build_payload, invoke_judge, _make_client  # noqa: E402
from backend.eval.judge_config import HUB_PRICING_USD_PER_1M, PRODUCTION_JUDGE_MODEL  # noqa: E402

MINISSET_PATH = REPO_ROOT / "backend/eval/datasets/_judge_minisset.json"
RESULTS_DIR = REPO_ROOT / "backend/eval/results"

REFUSAL_BEHAVIORS = ("refuse", "refusal_with_correction")
# Scalar anchors for the refusal-aware reduction (see module docstring).
REFUSAL_SCALAR_APPROPRIATE = 1.0
REFUSAL_SCALAR_MISMATCH = 0.0


def adapt_item(item: dict[str, Any]) -> dict[str, Any]:
    """Shape a static mini-set item into the production judge payload.

    `agent_answer` <- the recorded `answer`; a single synthesized tool call
    carries the joined `chunks` as `result_full` — faithfully what the human
    rater saw. Reuses `build_payload` unchanged.
    """
    agent_response = {
        "answer": item["answer"],
        "tool_calls": [
            {
                "name": "search",
                "args": {},
                "result_full": "\n\n".join(item.get("chunks", [])),
            }
        ],
    }
    return build_payload(item, agent_response)


def reduce_verdicts(expected_behavior: str, verdicts: dict[str, Any]) -> float | None:
    """Reduce the judge's four verdicts to one scalar; None = error, drop item."""
    refusal = verdicts.get("refusal_appropriateness") or {}
    factual = verdicts.get("factual_correctness") or {}
    if refusal.get("_error") or factual.get("_error"):
        return None
    if expected_behavior in REFUSAL_BEHAVIORS:
        verdict = refusal.get("verdict")
        if verdict == "appropriate":
            return REFUSAL_SCALAR_APPROPRIATE
        if verdict in ("should_answer", "should_refuse"):
            return REFUSAL_SCALAR_MISMATCH
        return None  # unparseable verdict
    score = factual.get("score")
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


class UsageTrackingClient:
    """Wraps the OpenAI client to accumulate token usage for cost estimation."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        resp = self._inner.chat.completions.create(**kwargs)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self.prompt_tokens += usage.prompt_tokens or 0
            self.completion_tokens += usage.completion_tokens or 0
        return resp


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Cost from MEASURED tokens x the pricing snapshot; None when un-priced."""
    p = HUB_PRICING_USD_PER_1M.get(model)
    if p is None:
        return None
    return prompt_tokens / 1_000_000 * p["input"] + completion_tokens / 1_000_000 * p["output"]


def _ranks(values: list[float]) -> list[float]:
    """Average-rank assignment (handles ties). 1-based ranks."""
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation = Pearson on average ranks. Stdlib only."""
    if len(xs) != len(ys) or len(xs) < 3:
        raise ValueError("need >=3 paired observations")
    return correlation(_ranks(xs), _ranks(ys))


def run_calibration(
    model: str,
    miniset_path: Path = MINISSET_PATH,
    *,
    verbose: bool = True,
) -> dict[str, Any]:
    """Score the mini-set with the production judge under `model`.

    Returns {model, spearman, n_valid, n_dropped, cost_usd, prompt_tokens,
    completion_tokens, items:[...]}. Raises on a fully-unreachable model
    (first call fails with a transport/auth error and no item succeeds).
    """
    data = json.loads(miniset_path.read_text(encoding="utf-8"))
    items = data["items"]
    client = UsageTrackingClient(_make_client())

    rows: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        t0 = time.time()
        payload = adapt_item(item)
        verdicts = invoke_judge(payload, model=model, client=client)
        scalar = reduce_verdicts(item["expected_behavior"], verdicts)
        rows.append(
            {
                "id": item["id"],
                "human_score": item["human_score"],
                "expected_behavior": item["expected_behavior"],
                "judge_scalar": scalar,
                "refusal_verdict": (verdicts.get("refusal_appropriateness") or {}).get("verdict"),
                "factual_score": (verdicts.get("factual_correctness") or {}).get("score"),
                "latency_ms": round((time.time() - t0) * 1000, 1),
            }
        )
        if verbose:
            print(
                f"  [{i + 1}/{len(items)}] {item['id']} human={item['human_score']} "
                f"behavior={item['expected_behavior']} -> scalar={scalar}"
            )

    valid = [r for r in rows if r["judge_scalar"] is not None]
    if len(valid) < 3:
        raise RuntimeError(f"model {model}: only {len(valid)} valid judgements — unreachable or broken")
    rho = spearman(
        [float(r["human_score"]) for r in valid],
        [float(r["judge_scalar"]) for r in valid],
    )
    return {
        "model": model,
        "spearman": round(rho, 4),
        "n_items": len(items),
        "n_valid": len(valid),
        "n_dropped": len(rows) - len(valid),
        "prompt_tokens": client.prompt_tokens,
        "completion_tokens": client.completion_tokens,
        "cost_usd": cost_usd(model, client.prompt_tokens, client.completion_tokens),
        "items": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate the production judge against the mini-set")
    parser.add_argument("--model", default=PRODUCTION_JUDGE_MODEL,
                        help=f"judge model override (default: {PRODUCTION_JUDGE_MODEL})")
    parser.add_argument("--miniset", type=Path, default=MINISSET_PATH)
    parser.add_argument("--out", type=Path, default=None,
                        help="results JSON path (default: backend/eval/results/judge-calibration-<model>-<ts>.json)")
    args = parser.parse_args(argv)

    print(f"[calib] production-judge harness x model {args.model}")
    result = run_calibration(args.model, args.miniset)
    result["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    result["miniset"] = str(args.miniset)

    out = args.out
    if out is None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        out = RESULTS_DIR / f"judge-calibration-{args.model}-{ts}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    cost = result["cost_usd"]
    print(f"\n[calib] saved -> {out}")
    print(f"  Spearman = {result['spearman']}  (n_valid={result['n_valid']}, dropped={result['n_dropped']})")
    print(f"  tokens   = {result['prompt_tokens']} in / {result['completion_tokens']} out"
          f"  cost = {'$%.4f' % cost if cost is not None else 'n/a (model not in pricing table)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
