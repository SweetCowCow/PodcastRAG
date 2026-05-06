"""Admin endpoints for browsing past RAG-eval runs.

Reads JSON reports written by `backend/eval/runners/run.py` from the results
directory. No DB persistence — the filesystem is source-of-truth for v1.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from app.schemas.admin_eval import EvalRunSummary, EvalRunListResponse, EvalRunDetailResponse

# backend/app/api/admin/eval_runs.py → backend/eval/results
RESULTS_DIR = Path(__file__).resolve().parents[3] / "eval" / "results"

router = APIRouter(prefix="/eval", tags=["admin-eval"])

# eval-{slug}-{run_id}.json — slug can contain hyphens, run_id is YYYYMMDDTHHMMSSZ
_FILENAME_RE = re.compile(r"^eval-(?P<slug>.+)-(?P<run_id>\d{8}T\d{6}Z)\.json$")


def _parse_filename(name: str) -> tuple[str, str] | None:
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    return m.group("slug"), m.group("run_id")


def _summarize(report: dict, run_id: str) -> EvalRunSummary:
    overall = report.get("metrics", {}).get("overall", {})
    return EvalRunSummary(
        dataset=report.get("dataset", ""),
        version=report.get("version", ""),
        run_id=run_id,
        backend=report.get("backend", ""),
        judge_model=report.get("judge_model"),
        top_k=int(report.get("top_k", 0)),
        n_items=int(report.get("n_items", 0)),
        recall_at_k_mean=overall.get("recall_at_k_mean"),
        mrr=overall.get("mrr"),
        judge_score_mean=overall.get("judge_score_mean"),
        latency_p95_ms=overall.get("latency_p95_ms"),
    )


@router.get("/runs", response_model=EvalRunListResponse)
async def list_eval_runs() -> EvalRunListResponse:
    """List past eval runs sorted newest first. Empty list if none yet."""
    if not RESULTS_DIR.exists():
        return EvalRunListResponse(runs=[])
    summaries: list[EvalRunSummary] = []
    for path in RESULTS_DIR.glob("eval-*.json"):
        parsed = _parse_filename(path.name)
        if parsed is None:
            continue
        _slug, run_id = parsed
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        summaries.append(_summarize(data, run_id))
    summaries.sort(key=lambda s: s.run_id, reverse=True)
    return EvalRunListResponse(runs=summaries)


@router.get("/runs/{run_id}", response_model=EvalRunDetailResponse)
async def get_eval_run(run_id: str) -> EvalRunDetailResponse:
    """Return the full JSON report for one run, or 404 if not found."""
    if not _FILENAME_RE.match(f"eval-x-{run_id}.json"):
        raise HTTPException(status_code=400, detail="invalid run_id format")
    if not RESULTS_DIR.exists():
        raise HTTPException(status_code=404, detail="run not found")
    matches = list(RESULTS_DIR.glob(f"eval-*-{run_id}.json"))
    if not matches:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    data = json.loads(matches[0].read_text(encoding="utf-8"))
    return EvalRunDetailResponse(report=data)
