"""Pydantic schemas for admin RAG-eval endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class EvalRunSummary(BaseModel):
    """One row per past eval run, suitable for a table listing."""

    model_config = ConfigDict(from_attributes=True)

    dataset: str
    version: str
    run_id: str
    backend: str
    judge_model: str | None = None
    top_k: int
    n_items: int
    recall_at_k_mean: float | None = None
    mrr: float | None = None
    judge_score_mean: float | None = None
    latency_p95_ms: float | None = None


class EvalRunListResponse(BaseModel):
    runs: list[EvalRunSummary]


class EvalRunDetailResponse(BaseModel):
    """Full report dict — opaque to the schema since downstream may add fields."""

    report: dict[str, Any]
