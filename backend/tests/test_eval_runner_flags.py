"""Tests for the v2.0 eval runner CLI flags: --canary / --persist-answers /
--checkpoint-every / --resume. All tests use the in-memory urlopen mock from
the existing runner test family.
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


def _fake_dataset(tmp_path: Path, n: int = 5, slug: str = "fake-show") -> Path:
    items = [
        {
            "id": f"t-{i}",
            "type": "fact",
            "question": f"q-{i}",
            "expected_answer_keywords": [],
            "ground_truth_chunk_ids": [f"ep:{EP_A}@{i * 10}.00"],
            "sentinel": False,
            "source_episode_id": EP_A,
        }
        for i in range(n)
    ]
    payload = {
        "show_slug": slug,
        "show_id": SHOW_ID,
        "version": "v1",
        "created_at": "2026-01-01",
        "items": items,
    }
    p = tmp_path / f"{slug}.json"
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


def _stub_urlopen():
    """Every /search returns a single chunk matching the gt of item 0 only.
    /query (if hit) returns a fixed answer. Used as a uniform stub when the
    test doesn't care about per-item retrieval details."""
    payload = {
        "results": [
            {"episode_id": EP_A, "start_time": 0.0, "end_time": 1.0, "text": "stub-chunk"},
        ]
    }

    def _u(req, *a, **kw):
        return _FakeResponse(payload)

    return _u


# ─── --canary ────────────────────────────────────────────────────────


def test_canary_3_processes_only_first_3(tmp_path):
    dataset = _fake_dataset(tmp_path, n=10)
    out_dir = tmp_path / "out"
    with patch.object(run_module.urllib.request, "urlopen", _stub_urlopen()):
        report = run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=out_dir,
            canary=3,
        )
    assert report["n_items"] == 3
    assert [it["id"] for it in report["items"]] == ["t-0", "t-1", "t-2"]
    # Output filename has `.canary` suffix
    assert list(out_dir.glob("eval-*.canary.json"))
    assert list(out_dir.glob("eval-*.canary.md"))


def test_canary_zero_rejected(tmp_path):
    dataset = _fake_dataset(tmp_path, n=3)
    rc = run_module.main([
        "--dataset", str(dataset),
        "--backend-url", "http://test",
        "--skip-judge",
        "--out-dir", str(tmp_path / "out"),
        "--canary", "0",
    ])
    assert rc == 2


def test_canary_omitted_runs_full(tmp_path):
    dataset = _fake_dataset(tmp_path, n=4)
    with patch.object(run_module.urllib.request, "urlopen", _stub_urlopen()):
        report = run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=tmp_path / "out",
        )
    assert report["n_items"] == 4


# ─── --persist-answers ────────────────────────────────────────────────


def test_persist_answers_includes_extra_fields(tmp_path):
    dataset = _fake_dataset(tmp_path, n=2)
    with patch.object(run_module.urllib.request, "urlopen", _stub_urlopen()):
        report = run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,  # judge off so answer stays empty string, but other fields populated
            out_dir=tmp_path / "out",
            persist_answers=True,
        )
    for it in report["items"]:
        assert "question" in it
        assert "retrieved_chunk_ids" in it
        assert "retrieved_texts" in it
        assert "answer" in it
        assert "retrieval_context_for_judge" in it


def test_persist_answers_default_lean_output(tmp_path):
    dataset = _fake_dataset(tmp_path, n=2)
    with patch.object(run_module.urllib.request, "urlopen", _stub_urlopen()):
        report = run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=tmp_path / "out",
        )
    for it in report["items"]:
        for key in ("answer", "retrieved_texts", "retrieval_context_for_judge", "question", "retrieved_chunk_ids"):
            assert key not in it, f"lean default must omit {key}"


# ─── --checkpoint-every + --resume ────────────────────────────────────


def test_checkpoint_written_every_n(tmp_path):
    dataset = _fake_dataset(tmp_path, n=4)
    out_dir = tmp_path / "out"
    cp_path = out_dir / ".checkpoint.json"

    # urlopen mock that snapshots the checkpoint file mid-run (after item 2).
    snapshots: list[dict] = []
    call = {"n": 0}

    def _u(req, *a, **kw):
        call["n"] += 1
        # checkpoint_every=2 → after items 0,1 finish (call 2), checkpoint should exist
        if cp_path.exists():
            snapshots.append(json.loads(cp_path.read_text()))
        return _FakeResponse({
            "results": [{"episode_id": EP_A, "start_time": 0.0, "end_time": 1.0, "text": "x"}]
        })

    with patch.object(run_module.urllib.request, "urlopen", _u):
        run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=out_dir,
            checkpoint_every=2,
        )
    # At some point during the run we should have seen a checkpoint with exactly 2 items
    assert any(len(s["items"]) == 2 for s in snapshots), f"never saw a 2-item checkpoint; snapshots={[len(s['items']) for s in snapshots]}"


def test_checkpoint_deleted_on_success(tmp_path):
    dataset = _fake_dataset(tmp_path, n=4)
    out_dir = tmp_path / "out"
    with patch.object(run_module.urllib.request, "urlopen", _stub_urlopen()):
        run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=out_dir,
            checkpoint_every=2,
        )
    assert not (out_dir / ".checkpoint.json").exists()


def test_resume_skips_processed(tmp_path):
    dataset = _fake_dataset(tmp_path, n=5)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # Hand-craft a checkpoint where 3 items are already done.
    cp = {
        "meta": {"dataset": str(dataset)},
        "items": [
            {"id": "t-0", "type": "fact", "recall_at_k": 1.0, "reciprocal_rank": 1.0, "judge_score": None, "latency_ms": 1.0},
            {"id": "t-1", "type": "fact", "recall_at_k": 1.0, "reciprocal_rank": 1.0, "judge_score": None, "latency_ms": 1.0},
            {"id": "t-2", "type": "fact", "recall_at_k": 1.0, "reciprocal_rank": 1.0, "judge_score": None, "latency_ms": 1.0},
        ],
    }
    cp_path = out_dir / ".checkpoint.json"
    cp_path.write_text(json.dumps(cp), encoding="utf-8")

    call_ids: list[str] = []

    def _u(req, *a, **kw):
        # We only need to handle /search calls (skip_judge=True). Caller index
        # corresponds to remaining items processed.
        call_ids.append(req.full_url)
        return _FakeResponse({
            "results": [{"episode_id": EP_A, "start_time": 0.0, "end_time": 1.0, "text": "x"}]
        })

    with patch.object(run_module.urllib.request, "urlopen", _u):
        report = run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=out_dir,
            resume_path=cp_path,
        )
    # Only 2 items (t-3, t-4) should have triggered urlopen
    assert len(call_ids) == 2
    # Final report covers all 5
    assert report["n_items"] == 5
    assert {it["id"] for it in report["items"]} == {"t-0", "t-1", "t-2", "t-3", "t-4"}


def test_resume_mismatched_dataset_rejects(tmp_path):
    dataset_a = _fake_dataset(tmp_path, n=3, slug="show-a")
    dataset_b = _fake_dataset(tmp_path, n=3, slug="show-b")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cp = {"meta": {"dataset": str(dataset_a)}, "items": []}
    cp_path = out_dir / ".checkpoint.json"
    cp_path.write_text(json.dumps(cp), encoding="utf-8")

    with pytest.raises(ValueError, match="dataset mismatch"):
        with patch.object(run_module.urllib.request, "urlopen", _stub_urlopen()):
            run_module.run_eval(
                dataset_path=dataset_b,
                backend_url="http://test",
                token="",
                top_k=5,
                skip_judge=True,
                out_dir=out_dir,
                resume_path=cp_path,
            )


def test_canary_and_resume_mutually_exclusive(tmp_path):
    dataset = _fake_dataset(tmp_path, n=3)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    cp_path = out_dir / ".checkpoint.json"
    cp_path.write_text(json.dumps({"meta": {"dataset": str(dataset)}, "items": []}), encoding="utf-8")
    rc = run_module.main([
        "--dataset", str(dataset),
        "--backend-url", "http://test",
        "--skip-judge",
        "--out-dir", str(out_dir),
        "--canary", "2",
        "--resume", str(cp_path),
    ])
    assert rc == 2


# ─── Back-compat ──────────────────────────────────────────────────────


def test_back_compat_no_flags_unchanged(tmp_path):
    """Without any new flags, runner produces the v1-ish report shape."""
    dataset = _fake_dataset(tmp_path, n=3)
    out_dir = tmp_path / "out"
    with patch.object(run_module.urllib.request, "urlopen", _stub_urlopen()):
        report = run_module.run_eval(
            dataset_path=dataset,
            backend_url="http://test",
            token="",
            top_k=5,
            skip_judge=True,
            out_dir=out_dir,
        )
    assert report["n_items"] == 3
    # No .canary suffix
    assert not list(out_dir.glob("eval-*.canary.json"))
    assert list(out_dir.glob("eval-fake-show-*.json"))
    # No checkpoint left behind
    assert not (out_dir / ".checkpoint.json").exists()
