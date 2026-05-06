"""Tests for the RAG eval runner — uses an in-memory fake backend.

Doesn't hit the network; mocks `urllib.request.urlopen` to return canned
search/query responses, then asserts the runner's report shape + metric
values.
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


def _fake_dataset(tmp_path: Path) -> Path:
    """A 4-item dataset covering all metric branches: hit, miss, neg, cross."""
    items = [
        {
            "id": "t-fact-hit",
            "type": "fact",
            "question": "鐵板麵的特別之處？",
            "expected_answer_keywords": ["鐵板麵"],
            "ground_truth_chunk_ids": [f"ep:{EP_A}@10.00"],
            "sentinel": True,
            "source_episode_id": EP_A,
        },
        {
            "id": "t-fact-miss",
            "type": "fact",
            "question": "誰說了 80%？",
            "expected_answer_keywords": ["80%"],
            "ground_truth_chunk_ids": [f"ep:{EP_A}@99.00"],
            "sentinel": False,
            "source_episode_id": EP_A,
        },
        {
            "id": "t-neg",
            "type": "negative",
            "question": "節目有提到 8 Mile 電影嗎？",
            "expected_answer_keywords": [],
            "ground_truth_chunk_ids": [],
            "sentinel": False,
            "source_episode_id": "",
        },
        {
            "id": "t-cross",
            "type": "cross-episode",
            "question": "迪拉的飲食習慣？",
            "expected_answer_keywords": ["飲食"],
            "ground_truth_chunk_ids": [f"ep:{EP_A}@20.00", f"ep:{EP_B}@30.00"],
            "sentinel": False,
            "source_episode_id": EP_A,
        },
    ]
    payload = {
        "show_slug": "fake-show",
        "show_id": SHOW_ID,
        "version": "v1",
        "created_at": "2026-01-01",
        "items": items,
    }
    p = tmp_path / "fake.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


class _FakeResponse:
    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode())

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _make_urlopen(canned_by_path: dict):
    def _urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        for path_suffix, payload in canned_by_path.items():
            if url.endswith(path_suffix):
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected URL in test: {url}")
    return _urlopen


def test_runner_aggregates_metrics(tmp_path):
    dataset = _fake_dataset(tmp_path)
    out_dir = tmp_path / "out"

    # Canned retrieval: t-fact-hit gets the gold chunk at rank 1; t-fact-miss
    # gets unrelated chunks; t-neg gets unrelated chunks (irrelevant for
    # negative — gt is empty so recall returns None); t-cross gets one of
    # two gold chunks at rank 2.
    search_responses = iter([
        # t-fact-hit
        {"results": [
            {"episode_id": EP_A, "start_time": 10.0, "end_time": 12.0, "text": "鐵板麵很厲害"},
            {"episode_id": EP_A, "start_time": 50.0, "end_time": 52.0, "text": "別的東西"},
        ]},
        # t-fact-miss
        {"results": [
            {"episode_id": EP_A, "start_time": 1.0, "end_time": 3.0, "text": "noise"},
        ]},
        # t-neg
        {"results": [
            {"episode_id": EP_A, "start_time": 5.0, "end_time": 7.0, "text": "noise"},
        ]},
        # t-cross (one of two gt found at rank 2)
        {"results": [
            {"episode_id": EP_A, "start_time": 99.0, "end_time": 101.0, "text": "filler"},
            {"episode_id": EP_B, "start_time": 30.0, "end_time": 32.0, "text": "gold-2"},
        ]},
    ])

    def _urlopen(req, *args, **kwargs):
        # Both /search and /query hit this; runner skip_judge=True so no /query.
        return _FakeResponse(next(search_responses))

    with patch.object(run_module.urllib.request, "urlopen", _urlopen):
        report = run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="fake",
            top_k=5,
            skip_judge=True,
            out_dir=out_dir,
        )

    # Per-item correctness
    items = {it["id"]: it for it in report["items"]}
    assert items["t-fact-hit"]["recall_at_k"] == 1.0
    assert items["t-fact-hit"]["reciprocal_rank"] == 1.0
    assert items["t-fact-miss"]["recall_at_k"] == 0.0
    assert items["t-fact-miss"]["reciprocal_rank"] == 0.0
    assert items["t-neg"]["recall_at_k"] is None  # negative excluded
    assert items["t-neg"]["reciprocal_rank"] is None
    assert items["t-cross"]["recall_at_k"] == 0.5  # 1 of 2
    assert items["t-cross"]["reciprocal_rank"] == 0.5  # rank 2

    # Aggregation excludes the negative
    overall = report["metrics"]["overall"]
    assert overall["n"] == 4
    assert overall["n_scored_retrieval"] == 3
    # Recall mean over (1.0, 0.0, 0.5) = 0.5
    assert overall["recall_at_k_mean"] == 0.5
    # MRR mean over (1.0, 0.0, 0.5) = 0.5
    assert overall["mrr"] == 0.5

    # By-type slicing
    by = report["metrics"]["by_type"]
    assert by["fact"]["n"] == 2
    assert by["fact"]["recall_at_k_mean"] == 0.5
    assert by["negative"]["n"] == 1
    assert by["negative"]["recall_at_k_mean"] is None
    assert by["cross-episode"]["mrr"] == 0.5

    # Files written
    json_files = list(out_dir.glob("eval-fake-show-*.json"))
    md_files = list(out_dir.glob("eval-fake-show-*.md"))
    assert len(json_files) == 1
    assert len(md_files) == 1
    md_text = md_files[0].read_text(encoding="utf-8")
    assert "Recall@5" in md_text
    assert "fact" in md_text


def test_runner_handles_retrieve_failure(tmp_path):
    """If retrieval blows up, item is recorded with empty chunks (recall=0)."""
    dataset = _fake_dataset(tmp_path)
    out_dir = tmp_path / "out"

    import urllib.error

    def _failing(req, *args, **kwargs):
        raise urllib.error.URLError("boom")

    with patch.object(run_module.urllib.request, "urlopen", _failing):
        report = run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=out_dir,
        )

    # All non-negative items should have recall_at_k == 0.0 (retrieved nothing)
    for item in report["items"]:
        if item["type"] == "negative":
            assert item["recall_at_k"] is None
        else:
            assert item["recall_at_k"] == 0.0
            assert item["reciprocal_rank"] == 0.0
