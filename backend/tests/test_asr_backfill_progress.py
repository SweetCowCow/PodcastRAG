"""Tests for backfill Celery tasks' progress reporting (EQ2e F8).

Spec: asr-correction-dictionary → Requirement
"Backfill jobs report progress and are cancellable".

Both tasks are bound (`bind=True`); each wraps the batch driver with a
progress callback that emits `update_state(PROGRESS, meta=...)`. These tests
inject a fake driver so no DB/LLM is touched, capture `update_state`, and
assert the current count rises monotonically and the terminal return dict
carries the accumulator fields.
"""
from __future__ import annotations

import uuid

from app.services import asr_correction, asr_detection_backfill
from app.workers import tasks
from app.workers.tasks import backfill_asr_corrections, detect_existing_episodes


def test_detect_existing_episodes_reports_progress(monkeypatch):
    async def fake_driver(session, show_id, *, progress_cb=None, **kwargs):
        progress_cb(1, 3, [])
        progress_cb(2, 3, [])
        progress_cb(3, 3, ["ep-x"])
        return {
            "processed": 3,
            "total": 3,
            "persisted": 5,
            "failed_episode_ids": ["ep-x"],
        }

    monkeypatch.setattr(
        asr_detection_backfill, "run_detection_backfill", fake_driver
    )
    captured: list[dict] = []
    monkeypatch.setattr(
        detect_existing_episodes,
        "update_state",
        lambda **kw: captured.append(kw),
    )

    result = detect_existing_episodes(str(uuid.uuid4()))

    currents = [c["meta"]["current"] for c in captured]
    assert currents == [1, 2, 3], "current must rise once per episode"
    assert all(c["meta"]["phase"] == "detect" for c in captured)
    assert captured[-1]["meta"]["failed_chunk_ids"] == ["ep-x"]
    assert result["persisted"] == 5
    assert result["failed_episode_ids"] == ["ep-x"]


def test_apply_backfill_reports_progress(monkeypatch):
    async def fake_backfill(session, *, progress_cb=None, **kwargs):
        progress_cb(1, 2, [])
        progress_cb(2, 2, ["chunk-9"])
        return asr_correction.BackfillReport(
            affected_transcripts=2,
            affected_segments=2,
            affected_chunks=3,
            failed_chunk_ids=["chunk-9"],
        )

    async def fake_step_config(session, key):
        return None

    monkeypatch.setattr(asr_correction, "backfill_corrections", fake_backfill)
    monkeypatch.setattr(tasks, "get_step_config", fake_step_config)
    captured: list[dict] = []
    monkeypatch.setattr(
        backfill_asr_corrections,
        "update_state",
        lambda **kw: captured.append(kw),
    )

    result = backfill_asr_corrections(show_id=str(uuid.uuid4()))

    currents = [c["meta"]["current"] for c in captured]
    assert currents == [1, 2], "current must rise once per transcript"
    assert all(c["meta"]["phase"] == "apply" for c in captured)
    assert captured[-1]["meta"]["failed_chunk_ids"] == ["chunk-9"]
    assert result["failed_chunk_ids"] == ["chunk-9"]
