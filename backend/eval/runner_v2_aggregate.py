"""v2 aggregate report builder for chat-rag eval.

Per-design_type + per-indicator. Does NOT compute a cross-design-type single mean
(per rag-eval-runner spec requirement).

Input: list of {'item_id', 'design_type', 'indicators': {name: {score, passed, details}|None}}
Output: report dict per spec acceptance criteria.

Markdown rendering produces one table per design_type plus a single by-indicator
summary table.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def aggregate(item_results: list[dict[str, Any]]) -> dict[str, Any]:
    by_dt: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n_items": 0, "indicators": defaultdict(lambda: {"scores": [], "passed": 0})}
    )
    overall_ind: dict[str, dict[str, Any]] = defaultdict(lambda: {"scores": [], "passed": 0})

    for r in item_results:
        dt = r.get("design_type") or "unknown"
        by_dt[dt]["n_items"] += 1
        for ind_name, ind in (r.get("indicators") or {}).items():
            if ind is None:
                continue
            score = ind.get("score")
            if score is None:
                continue
            by_dt[dt]["indicators"][ind_name]["scores"].append(score)
            by_dt[dt]["indicators"][ind_name]["passed"] += 1 if ind.get("passed") else 0
            overall_ind[ind_name]["scores"].append(score)
            overall_ind[ind_name]["passed"] += 1 if ind.get("passed") else 0

    def _finalize(d: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, agg in d.items():
            scores = agg["scores"]
            n = len(scores)
            out[name] = {
                "n_scored": n,
                "mean": (sum(scores) / n) if n else None,
                "passed_count": agg["passed"],
            }
        return out

    return {
        "by_design_type": {
            dt: {
                "n_items": data["n_items"],
                "indicators": _finalize(data["indicators"]),
            }
            for dt, data in by_dt.items()
        },
        "overall": {
            "n_items_total": len(item_results),
            "by_indicator": _finalize(overall_ind),
        },
    }


def render_markdown(
    aggregate_report: dict[str, Any],
    *,
    title: str = "Chat-RAG v2 eval baseline",
    judge_prompt_sha256: str | None = None,
) -> str:
    lines: list[str] = [f"# {title}", ""]
    if judge_prompt_sha256:
        lines.append(f"judge_prompt_sha256: {judge_prompt_sha256}")
        lines.append("")

    by_dt = aggregate_report.get("by_design_type", {})
    for dt, data in sorted(by_dt.items()):
        n = data["n_items"]
        lines.append(f"## {dt} (n={n})")
        lines.append("")
        lines.append("| Indicator | n_scored | mean | passed_count |")
        lines.append("|---|---:|---:|---:|")
        inds = data.get("indicators", {})
        for name in sorted(inds):
            ind = inds[name]
            mean_str = "n/a" if ind["mean"] is None else f"{ind['mean']:.3f}"
            lines.append(f"| {name} | {ind['n_scored']} | {mean_str} | {ind['passed_count']} |")
        lines.append("")

    overall = aggregate_report.get("overall", {})
    lines.append(f"## Summary by indicator (n_items_total={overall.get('n_items_total', 0)})")
    lines.append("")
    lines.append("| Indicator | n_scored | mean | passed_count |")
    lines.append("|---|---:|---:|---:|")
    for name in sorted(overall.get("by_indicator", {})):
        ind = overall["by_indicator"][name]
        mean_str = "n/a" if ind["mean"] is None else f"{ind['mean']:.3f}"
        lines.append(f"| {name} | {ind['n_scored']} | {mean_str} | {ind['passed_count']} |")
    lines.append("")
    lines.append(
        "> Per indicator only items where the indicator applied are counted "
        "(N varies by indicator). No cross-design-type single mean is published."
    )
    return "\n".join(lines)


def dataset_schema_version(dataset: dict[str, Any]) -> str:
    """Return schema_version string; 'v1' if not declared."""
    return dataset.get("schema_version") or "v1"
