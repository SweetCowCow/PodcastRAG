"""Smoke tests for /admin/rrf/sweep endpoint (change: retrieval-cross-episode-recall-improvement).

Verifies:
- require_admin gate is in place (anonymous → 401)
- body schema validates RRFWeightTuple shape
- after sweep run, rag.RRF_WEIGHTS is restored to original values (no state leak)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import rag


def test_rrf_sweep_router_has_admin_dependency():
    """Router is mounted under /admin which carries require_admin Depends."""
    from app.api.admin import router as admin_root_router
    from app.api.admin.rrf_sweep import router as rrf_router

    # Sub-router itself doesn't list require_admin — it's inherited from parent
    assert rrf_router.prefix == "/rrf"
    # admin_root_router includes rrf_router; admin_root_router has require_admin dep
    dep_names = [
        d.dependency.__name__ if hasattr(d.dependency, "__name__") else str(d.dependency)
        for d in (admin_root_router.dependencies or [])
    ]
    assert any("require_admin" in n for n in dep_names), f"expected require_admin in {dep_names}"


def test_rrf_weight_tuple_rejects_non_positive():
    """Pydantic Field(gt=0) refuses zero / negative weights."""
    from pydantic import ValidationError

    from app.api.admin.rrf_sweep import RRFWeightTuple

    # happy path
    RRFWeightTuple(chunk=1.0, description=0.7, title=0.5)

    with pytest.raises(ValidationError):
        RRFWeightTuple(chunk=0.0, description=0.7, title=0.5)
    with pytest.raises(ValidationError):
        RRFWeightTuple(chunk=-0.5, description=0.7, title=0.5)


@pytest.mark.asyncio
async def test_sweep_restores_rrf_weights_after_run(monkeypatch):
    """rag.RRF_WEIGHTS must equal original mapping after sweep, even when monkey-patched."""
    from app.api.admin.rrf_sweep import RRFSweepRequest, RRFWeightTuple, rrf_sweep

    original = dict(rag.RRF_WEIGHTS)

    # Stub _retrieve_and_grade so we don't need a real DB
    from app.api.admin import rrf_sweep as mod

    async def fake_retrieve_and_grade(db, show_id, item):
        return {"item_id": item["id"], "score": 0.5, "must_hits": 1, "must_total": 2, "either_group_hit": False, "top5": []}

    monkeypatch.setattr(mod, "_retrieve_and_grade", fake_retrieve_and_grade)

    # Stub dataset loader to return a minimal item
    def fake_load_items_indexed():
        return {"b20": {"id": "b20", "design_type": "cross_episode"}}

    monkeypatch.setattr(mod, "_load_items_indexed", fake_load_items_indexed)

    req = RRFSweepRequest(
        candidates=[
            RRFWeightTuple(chunk=1.0, description=0.7, title=0.5),
            RRFWeightTuple(chunk=1.0, description=5.0, title=0.5),  # extreme
        ],
        mini_set_ids=["b20"],
    )

    resp = await rrf_sweep(req, db=MagicMock())

    # Endpoint ran both candidates
    assert len(resp["candidates"]) == 2
    # baseline_index points to description=0.7 entry
    assert resp["baseline_index"] == 0
    # RRF_WEIGHTS restored to original — no leak
    assert dict(rag.RRF_WEIGHTS) == original


@pytest.mark.asyncio
async def test_sweep_restores_rrf_weights_even_on_exception(monkeypatch):
    """finally: rag.RRF_WEIGHTS restored even if _retrieve_and_grade raises."""
    from app.api.admin.rrf_sweep import RRFSweepRequest, RRFWeightTuple, rrf_sweep
    from app.api.admin import rrf_sweep as mod
    from fastapi import HTTPException

    original = dict(rag.RRF_WEIGHTS)

    async def boom(db, show_id, item):
        raise RuntimeError("simulated retrieval failure")

    monkeypatch.setattr(mod, "_retrieve_and_grade", boom)
    monkeypatch.setattr(mod, "_load_items_indexed", lambda: {"b20": {"id": "b20"}})

    req = RRFSweepRequest(
        candidates=[RRFWeightTuple(chunk=1.0, description=5.0, title=0.5)],
        mini_set_ids=["b20"],
    )

    with pytest.raises(RuntimeError):
        await rrf_sweep(req, db=MagicMock())

    assert dict(rag.RRF_WEIGHTS) == original, "RRF_WEIGHTS must be restored even on exception"
