"""Judge model bake-off — aligned harness (change `r1-3-j-judge-harness-align`).

Runs the PRODUCTION judge path (`backend/eval/judge_chat_v2.py` +
`backend/eval/prompts/chat_judge_v2.md`) over the field-complete 40-item
mini-set for each candidate model, via
`backend.scripts.llm_judge_calibration.run_calibration` (adapter + refusal-
aware scalar). The old DeepEval GEval rubric is gone — it was a second
stand-in judge, the exact drift this change removes.

Two-phase flow (the pass threshold is set from the OBSERVED distribution,
not the historical 0.7 which no model ever met on the old harness):

1. Sweep:    python -m backend.eval.scripts.judge_bakeoff
             -> runs all candidates, prints the Spearman/cost table, persists
                backend/eval/results/judge-bakeoff-aligned-<ts>.json
                (threshold/selection fields null, to be filled by phase 2)
2. Select:   python -m backend.eval.scripts.judge_bakeoff \
                 --select-from <results.json> --threshold 0.65 [--write-config]
             -> records the threshold, applies the selection rule (highest
                Spearman among passers, lowest cost_usd on ties) and, with
                --write-config, sets PRODUCTION_JUDGE_MODEL in judge_config.py.
                Zero passers -> config NOT modified; recommends the C fallback
                (per-question human re-score).

A candidate that is unreachable on the AI Hub endpoint is reported and
skipped — never assumed to pass or fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.llm_judge_calibration import MINISSET_PATH, run_calibration  # noqa: E402

RESULTS_DIR = REPO_ROOT / "backend/eval/results"
CONFIG_PATH = REPO_ROOT / "backend/eval/judge_config.py"

CANDIDATES = [
    "gpt-5.1",
    "gemini-3.5-flash",
    "claude-haiku-4-5",
    "gpt-5-nano",
    "gemini-2.5-flash-lite",
]


def run_sweep(miniset_path: Path) -> dict:
    rows: list[dict] = []
    skipped: list[dict] = []
    for model in CANDIDATES:
        print(f"\n[bakeoff] === {model} ===")
        try:
            r = run_calibration(model, miniset_path)
        except Exception as exc:  # noqa: BLE001 — unreachable model: report & skip
            print(f"[warn] {model} unreachable/failed — skipped: {exc}", file=sys.stderr)
            skipped.append({"model": model, "error": str(exc)[:300]})
            continue
        rows.append(
            {
                "model": r["model"],
                "spearman": r["spearman"],
                "pass_threshold": None,  # filled by --select-from
                "cost_usd": round(r["cost_usd"], 4) if r["cost_usd"] is not None else None,
                "n_valid": r["n_valid"],
                "n_dropped": r["n_dropped"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
            }
        )
    rows.sort(key=lambda r: r["spearman"], reverse=True)
    return {
        "harness": "aligned-production-judge (judge_chat_v2 + chat_judge_v2.md, refusal-aware scalar)",
        "miniset": str(miniset_path),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "threshold": None,
        "selected_model": None,
        "selection_note": None,
        "candidates": rows,
        "skipped": skipped,
    }


def print_table(result: dict) -> None:
    thr = result.get("threshold")
    print(f"\n{'model':<28} {'spearman':>9} {'pass':>6} {'cost_usd':>10}")
    print("-" * 58)
    for r in result["candidates"]:
        cost = f"{r['cost_usd']:.4f}" if r["cost_usd"] is not None else "n/a"
        passed = "-" if thr is None else str(r["spearman"] >= thr)
        print(f"{r['model']:<28} {r['spearman']:>9.4f} {passed:>6} {cost:>10}")
    for s in result.get("skipped", []):
        print(f"{s['model']:<28} {'SKIPPED (unreachable)':>26}")
    if thr is not None:
        print(f"\nthreshold = {thr} | selected = {result.get('selected_model')}")
    print()


def select(result: dict, threshold: float) -> dict:
    """Apply the selection rule and record it into the result dict."""
    result["threshold"] = threshold
    for r in result["candidates"]:
        r["pass_threshold"] = r["spearman"] >= threshold
    passers = [r for r in result["candidates"] if r["pass_threshold"]]
    if not passers:
        result["selected_model"] = None
        result["selection_note"] = (
            "zero candidates met the threshold — PRODUCTION_JUDGE_MODEL NOT modified; "
            "recommended next step: C fallback (per-question human re-score of the mini-set)"
        )
        return result
    best = max(passers, key=lambda r: (r["spearman"], -(r["cost_usd"] if r["cost_usd"] is not None else float("inf"))))
    result["selected_model"] = best["model"]
    result["selection_note"] = (
        f"highest Spearman among threshold passers (cost tie-break): "
        f"{best['model']} spearman={best['spearman']} cost_usd={best['cost_usd']}"
    )
    return result


def write_config(model: str) -> None:
    src = CONFIG_PATH.read_text(encoding="utf-8")
    out = []
    for line in src.splitlines(keepends=True):
        if line.startswith("PRODUCTION_JUDGE_MODEL"):
            out.append(f'PRODUCTION_JUDGE_MODEL = "{model}"\n')
        else:
            out.append(line)
    CONFIG_PATH.write_text("".join(out), encoding="utf-8")
    print(f"[config] PRODUCTION_JUDGE_MODEL = {model} written to {CONFIG_PATH}")
    print("[config] REMINDER: update the module docstring so the comment names the same model.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aligned judge bake-off (production-judge harness)")
    parser.add_argument("--miniset", type=Path, default=MINISSET_PATH)
    parser.add_argument("--select-from", type=Path, default=None,
                        help="existing sweep results JSON to run selection on (skips re-running models)")
    parser.add_argument("--threshold", type=float, default=None,
                        help="pass threshold, set from the observed distribution (required for selection)")
    parser.add_argument("--write-config", action="store_true",
                        help="write the selected model into judge_config.py (requires --threshold)")
    args = parser.parse_args(argv)

    if args.select_from is not None:
        if args.threshold is None:
            print("--select-from requires --threshold", file=sys.stderr)
            return 2
        result = json.loads(args.select_from.read_text(encoding="utf-8"))
        result = select(result, args.threshold)
        args.select_from.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print_table(result)
        if result["selected_model"] is None:
            print(result["selection_note"], file=sys.stderr)
            return 1
        if args.write_config:
            write_config(result["selected_model"])
        return 0

    result = run_sweep(args.miniset)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"judge-bakeoff-aligned-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print_table(result)
    print(f"[bakeoff] results -> {out}")
    print("[bakeoff] next: --select-from <results.json> --threshold <value from distribution>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
