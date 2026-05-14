"""Dispatch & aggregation tests for the runner's eval_mode paths
(chunk_id / open_set_lenient / enumeration) introduced by the
eval-runner-enumeration-scope change.

All tests stub backend HTTP with a fake urlopen so no live server is required.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.runners import run as run_module  # noqa: E402


SHOW_ID = "00000000-0000-0000-0000-000000000001"
EP_A = "aaaa1111-1111-1111-1111-111111111111"
EP_B = "bbbb2222-2222-2222-2222-222222222222"
EP_C = "cccc3333-3333-3333-3333-333333333333"


class _FakeResponse:
    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode())

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_with_chunks(results: list[dict]):
    payload = {"results": results}
    return lambda req, *a, **kw: _FakeResponse(payload)


def _write_dataset(tmp_path: Path, items: list[dict], slug: str = "fake") -> Path:
    p = tmp_path / f"{slug}.json"
    p.write_text(json.dumps({
        "show_slug": slug, "show_id": SHOW_ID, "version": "v1",
        "created_at": "2026-01-01", "items": items,
    }), encoding="utf-8")
    return p


def _run(dataset: Path, out_dir: Path, top_k: int = 5):
    return run_module.run_eval(
        dataset_path=dataset, backend_url="http://test", token="",
        top_k=top_k, skip_judge=True, out_dir=out_dir,
    )


def test_chunk_id_mode_unchanged_recall(tmp_path):
    items = [{
        "id": "q1", "type": "fact", "eval_mode": "chunk_id",
        "question": "?", "expected_answer_keywords": [],
        "ground_truth_chunk_ids": [f"ep:{EP_A}@10.00"],
        "sentinel": False, "source_episode_id": EP_A,
    }]
    ds = _write_dataset(tmp_path, items)
    stub = _stub_with_chunks([{"episode_id": EP_A, "start_time": 10.0, "end_time": 11.0, "text": ""}])
    with patch.object(run_module.urllib.request, "urlopen", stub):
        rep = _run(ds, tmp_path / "out")
    assert rep["items"][0]["eval_mode"] == "chunk_id"
    assert rep["items"][0]["recall_at_k"] == 1.0
    assert rep["items"][0]["episode_set_recall"] is None
    assert rep["metrics"]["chunk_based"]["recall_at_k_mean"] == 1.0
    assert rep["metrics"]["enumeration"]["n"] == 0


def test_open_set_lenient_any_hit_is_one(tmp_path):
    # Three anchors, retrieval hits only one — under chunk_id mode this would be 1/3,
    # under open_set_lenient it should be 1.0.
    items = [{
        "id": "q1", "type": "cross-episode", "eval_mode": "open_set_lenient",
        "question": "?", "expected_answer_keywords": [],
        "ground_truth_chunk_ids": [
            f"ep:{EP_A}@10.00", f"ep:{EP_A}@20.00", f"ep:{EP_B}@5.00"
        ],
        "sentinel": False, "source_episode_id": EP_A,
    }]
    ds = _write_dataset(tmp_path, items)
    stub = _stub_with_chunks([{"episode_id": EP_A, "start_time": 20.0, "end_time": 21.0, "text": ""}])
    with patch.object(run_module.urllib.request, "urlopen", stub):
        rep = _run(ds, tmp_path / "out")
    assert rep["items"][0]["eval_mode"] == "open_set_lenient"
    assert rep["items"][0]["recall_at_k"] == 1.0
    assert rep["metrics"]["chunk_based"]["recall_at_k_mean"] == 1.0


def test_open_set_lenient_no_hit_is_zero(tmp_path):
    items = [{
        "id": "q1", "type": "cross-episode", "eval_mode": "open_set_lenient",
        "question": "?", "expected_answer_keywords": [],
        "ground_truth_chunk_ids": [f"ep:{EP_A}@10.00"],
        "sentinel": False, "source_episode_id": EP_A,
    }]
    ds = _write_dataset(tmp_path, items)
    # Retrieval returns a chunk from EP_C — no overlap with EP_A anchor.
    stub = _stub_with_chunks([{"episode_id": EP_C, "start_time": 5.0, "end_time": 6.0, "text": ""}])
    with patch.object(run_module.urllib.request, "urlopen", stub):
        rep = _run(ds, tmp_path / "out")
    assert rep["items"][0]["recall_at_k"] == 0.0


def test_enumeration_episode_set_recall(tmp_path):
    # Expected = 5 episodes, retrieval covers 2 → 0.4
    expected = [EP_A, EP_B, EP_C, "dddd4444-4444-4444-4444-444444444444",
                "eeee5555-5555-5555-5555-555555555555"]
    items = [{
        "id": "q1", "type": "cross-episode", "eval_mode": "enumeration",
        "question": "?", "expected_answer_keywords": [],
        "ground_truth_chunk_ids": [],
        "expected_episode_ids": expected,
        "sentinel": False, "source_episode_id": EP_A,
    }]
    ds = _write_dataset(tmp_path, items)
    stub = _stub_with_chunks([
        {"episode_id": EP_A, "start_time": 0.0, "end_time": 1.0, "text": ""},
        {"episode_id": EP_C, "start_time": 0.0, "end_time": 1.0, "text": ""},
        {"episode_id": "zzzz9999-9999-9999-9999-999999999999", "start_time": 0.0, "end_time": 1.0, "text": ""},
    ])
    with patch.object(run_module.urllib.request, "urlopen", stub):
        rep = _run(ds, tmp_path / "out")
    rec = rep["items"][0]
    assert rec["eval_mode"] == "enumeration"
    assert rec["recall_at_k"] is None
    assert rec["episode_set_recall"] == pytest.approx(0.4)
    assert rep["metrics"]["enumeration"]["n"] == 1
    assert rep["metrics"]["enumeration"]["episode_set_recall_mean"] == pytest.approx(0.4)
    # Enumeration items do NOT pollute chunk_based aggregate
    assert rep["metrics"]["chunk_based"]["n"] == 0
    assert rep["metrics"]["chunk_based"]["recall_at_k_mean"] is None


def test_mixed_dataset_segregates_metrics(tmp_path):
    items = [
        {  # chunk_id hit
            "id": "qc", "type": "fact", "eval_mode": "chunk_id",
            "question": "?", "expected_answer_keywords": [],
            "ground_truth_chunk_ids": [f"ep:{EP_A}@10.00"],
            "sentinel": False, "source_episode_id": EP_A,
        },
        {  # enumeration partial
            "id": "qe", "type": "cross-episode", "eval_mode": "enumeration",
            "question": "?", "expected_answer_keywords": [],
            "ground_truth_chunk_ids": [],
            "expected_episode_ids": [EP_A, EP_B],
            "sentinel": False, "source_episode_id": EP_A,
        },
    ]
    ds = _write_dataset(tmp_path, items)
    # Every retrieval returns the same set: chunk from EP_A.
    stub = _stub_with_chunks([{"episode_id": EP_A, "start_time": 10.0, "end_time": 11.0, "text": ""}])
    with patch.object(run_module.urllib.request, "urlopen", stub):
        rep = _run(ds, tmp_path / "out")
    assert rep["metrics"]["chunk_based"]["n"] == 1
    assert rep["metrics"]["chunk_based"]["recall_at_k_mean"] == 1.0
    assert rep["metrics"]["enumeration"]["n"] == 1
    assert rep["metrics"]["enumeration"]["episode_set_recall_mean"] == 0.5


def test_negative_chunk_id_excluded_from_mean(tmp_path):
    items = [
        {
            "id": "qf", "type": "fact", "eval_mode": "chunk_id",
            "question": "?", "expected_answer_keywords": [],
            "ground_truth_chunk_ids": [f"ep:{EP_A}@10.00"],
            "sentinel": False, "source_episode_id": EP_A,
        },
        {  # negative — empty gt; expected to be excluded from chunk mean
            "id": "qn", "type": "negative", "eval_mode": "chunk_id",
            "question": "?", "expected_answer_keywords": [],
            "ground_truth_chunk_ids": [],
            "sentinel": False, "source_episode_id": EP_A,
        },
    ]
    ds = _write_dataset(tmp_path, items)
    stub = _stub_with_chunks([{"episode_id": EP_A, "start_time": 10.0, "end_time": 11.0, "text": ""}])
    with patch.object(run_module.urllib.request, "urlopen", stub):
        rep = _run(ds, tmp_path / "out")
    # n counts both, but recall_at_k_mean averages only the scored one.
    assert rep["metrics"]["chunk_based"]["n"] == 2
    assert rep["metrics"]["chunk_based"]["n_scored_retrieval"] == 1
    assert rep["metrics"]["chunk_based"]["recall_at_k_mean"] == 1.0


def test_markdown_report_renders_two_rows(tmp_path):
    items = [
        {
            "id": "qe", "type": "cross-episode", "eval_mode": "enumeration",
            "question": "?", "expected_answer_keywords": [],
            "ground_truth_chunk_ids": [],
            "expected_episode_ids": [EP_A, EP_B],
            "sentinel": False, "source_episode_id": EP_A,
        },
    ]
    ds = _write_dataset(tmp_path, items)
    stub = _stub_with_chunks([{"episode_id": EP_A, "start_time": 0.0, "end_time": 1.0, "text": ""}])
    with patch.object(run_module.urllib.request, "urlopen", stub):
        _run(ds, tmp_path / "out")
    md = next((tmp_path / "out").glob("eval-*.md")).read_text(encoding="utf-8")
    assert "Recall@5 (chunk" in md
    assert "Episode Set Recall (enumeration" in md
