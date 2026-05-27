"""Diff two chat-rag v2 baseline JSON files into a Markdown table.

Used by the eval-baseline-citation-bug-revalidation case study to compare polluted
(pre `287e73b`) baselines against the post-fix clean baseline. Designed for local
ad-hoc use; intentionally minimal (no aggregation reshuffle, no judge re-run).

Usage:
    python -m backend.eval.scripts.diff_baselines \\
        --old backend/eval/results/_polluted-baselines/voyage-4.4-r2-20260527T013405.json \\
        --new backend/eval/results/baseline-post-citation-fix-2026-05-27.json \\
        --dataset backend/eval/datasets/extended-multi-turn-40.json \\
        --output docs/case-studies/baselines-diff-2026-05-27.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _index_results(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["item_id"]: r for r in report.get("results", [])}


def _indicator(r: dict[str, Any], name: str) -> float | None:
    inds = r.get("indicators") or {}
    cell = inds.get(name) or {}
    score = cell.get("score")
    return score if isinstance(score, (int, float)) else None


def _verdict(delta: float | None) -> str:
    if delta is None:
        return "data_missing"
    if abs(delta) < 1e-6:
        return "unchanged"
    return "improved" if delta > 0 else "regressed"


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(b - a, 4)


def _trunc(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


def _question_for(item_id: str, dataset_items: dict[str, dict[str, Any]]) -> str:
    item = dataset_items.get(item_id) or {}
    if item.get("is_multi_turn"):
        turns = item.get("turns") or []
        return " // ".join((t.get("question") or "")[:40] for t in turns)
    return item.get("question") or ""


def diff_to_markdown(
    *,
    old: dict[str, Any],
    new: dict[str, Any],
    dataset: dict[str, Any],
    old_label: str,
    new_label: str,
) -> str:
    old_idx = _index_results(old)
    new_idx = _index_results(new)
    dataset_items = {it["id"]: it for it in dataset.get("items", [])}

    all_ids = sorted(set(old_idx) | set(new_idx))
    lines = [
        f"# Baseline diff — {old_label} vs {new_label}",
        "",
        f"- old: `{old_label}` ({len(old_idx)} items, {old.get('provenance', {}).get('backend_commit', 'unknown')})",
        f"- new: `{new_label}` ({len(new_idx)} items, {new.get('provenance', {}).get('backend_commit', 'unknown')})",
        f"- overlap: {len(set(old_idx) & set(new_idx))} items",
        "",
        "| record_id | design_type | question | cr_old | cr_new | Δcr | fc_old | fc_new | Δfc | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item_id in all_ids:
        old_r = old_idx.get(item_id)
        new_r = new_idx.get(item_id)
        ref = new_r or old_r or {}
        dt = ref.get("design_type") or "?"
        q = _trunc(_question_for(item_id, dataset_items), 60)
        cr_old = _indicator(old_r or {}, "chunk_recall_grouped") if old_r else None
        cr_new = _indicator(new_r or {}, "chunk_recall_grouped") if new_r else None
        fc_old = _indicator(old_r or {}, "factual_correctness") if old_r else None
        fc_new = _indicator(new_r or {}, "factual_correctness") if new_r else None
        d_cr = _delta(cr_old, cr_new)
        d_fc = _delta(fc_old, fc_new)
        verdict = _verdict(d_cr) if d_cr is not None else _verdict(d_fc)
        if old_r is None:
            verdict = "new_only"
        elif new_r is None:
            verdict = "old_only"

        def fmt(v: float | None) -> str:
            return "—" if v is None else f"{v:.3f}"

        lines.append(
            f"| {item_id} | {dt} | {q} | {fmt(cr_old)} | {fmt(cr_new)} | {fmt(d_cr)} | "
            f"{fmt(fc_old)} | {fmt(fc_new)} | {fmt(d_fc)} | {verdict} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, type=Path)
    ap.add_argument("--new", required=True, type=Path)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    old = json.loads(args.old.read_text(encoding="utf-8"))
    new = json.loads(args.new.read_text(encoding="utf-8"))
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    md = diff_to_markdown(
        old=old,
        new=new,
        dataset=dataset,
        old_label=args.old.name,
        new_label=args.new.name,
    )
    args.output.write_text(md, encoding="utf-8")
    print(f"✓ wrote {args.output} ({len(md.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
