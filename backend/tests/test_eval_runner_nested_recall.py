"""Tests for `_run_nested_eval` Recall@K plumbing in `run_chat_agent_eval`.

Covers the `multi-turn-40-add-recall-ground-truth` change: nested-schema
runner SHALL compute Recall@K per turn when `ground_truth_chunk_ids` is
non-null and skip / null otherwise; aggregate carries `recall_at_k_mean`
and `n_scored_recall`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))

# Import after sys.path is set so the script is importable as a module.
import run_chat_agent_eval as runner  # noqa: E402


def _mk_turn(question: str, gt: list[str] | None) -> dict:
    return {
        "question": question,
        "expected_tool_calls_required": [],
        "expected_tool_calls_acceptable": [],
        "expected_answer_keywords": [],
        "ground_truth_chunk_ids": gt,
    }


def _mk_item(item_id: str, turns: list[dict], is_multi_turn: bool = False, design_type: str = "deep_dive") -> dict:
    return {
        "id": item_id,
        "is_multi_turn": is_multi_turn,
        "design_type": design_type,
        "source": "test:fixture",
        "turns": turns,
    }


def _stub_search_returning(chunk_ids: list[str]):
    """Build a `_search` stub returning the given chunk_ids verbatim."""
    return lambda *a, **kw: list(chunk_ids)


def _stub_query_chat_with_trace(*args, **kwargs):
    return {"answer": "stub answer", "tool_calls": []}


def test_recall_computed_when_ground_truth_present():
    items = [
        _mk_item("t1", [_mk_turn("q1", ["ep:abc@10.0", "ep:abc@20.0"])]),
    ]
    with patch.object(runner, "_search", side_effect=_stub_search_returning(["ep:abc@10.0"])), \
         patch.object(runner, "_query_chat_with_trace", side_effect=_stub_query_chat_with_trace):
        per_turn, _ = runner._run_nested_eval(items, "show", "http://x", "tok", top_k=5)
    assert per_turn[0]["recall_at_k"] == pytest.approx(0.5)


def test_recall_skipped_when_ground_truth_null():
    items = [
        _mk_item("t1", [_mk_turn("q1", None)]),
    ]
    with patch.object(runner, "_search", side_effect=_stub_search_returning(["ep:abc@10.0"])) as m, \
         patch.object(runner, "_query_chat_with_trace", side_effect=_stub_query_chat_with_trace):
        per_turn, _ = runner._run_nested_eval(items, "show", "http://x", "tok", top_k=5)
    assert per_turn[0]["recall_at_k"] is None
    # search SHALL NOT be called when GT is null (only chat endpoint runs)
    m.assert_not_called()


def test_recall_skipped_when_ground_truth_empty_list():
    items = [
        _mk_item("t1", [_mk_turn("q1", [])]),
    ]
    with patch.object(runner, "_search", side_effect=_stub_search_returning(["ep:abc@10.0"])) as m, \
         patch.object(runner, "_query_chat_with_trace", side_effect=_stub_query_chat_with_trace):
        per_turn, _ = runner._run_nested_eval(items, "show", "http://x", "tok", top_k=5)
    assert per_turn[0]["recall_at_k"] is None
    m.assert_not_called()


def test_aggregate_recall_mean_and_n_scored():
    """run_eval (the top-level) populates aggregate.recall_at_k_mean from
    per-turn entries; mixed null and scored turns must aggregate correctly."""
    dataset = {
        "show_id": "show-1",
        "items": [
            _mk_item("t1", [_mk_turn("q1", ["ep:abc@10.0"])]),
            _mk_item("t2", [_mk_turn("q2", None)]),
            _mk_item("t3", [_mk_turn("q3", ["ep:def@5.0", "ep:def@15.0"])]),
        ],
    }
    # search alternates returns per turn — use a side-effect list
    search_returns = iter([
        ["ep:abc@10.0"],         # t1 → recall 1.0
        ["ep:def@5.0"],          # t3 → recall 0.5
    ])
    with patch.object(runner, "_search", side_effect=lambda *a, **kw: next(search_returns)), \
         patch.object(runner, "_query_chat_with_trace", side_effect=_stub_query_chat_with_trace), \
         patch.object(runner.Path, "read_text", return_value=__import__("json").dumps(dataset)):
        out = runner.run_eval(
            dataset_path=Path("ignored.json"),
            backend_url="http://x",
            auth_token="tok",
            top_k=5,
            label="test",
        )
    agg = out["aggregate"]
    assert agg["schema"] == "nested-multi-turn"
    assert agg["n_scored_recall"] == 2
    assert agg["recall_at_k_mean"] == pytest.approx(round(mean([1.0, 0.5]), 4))
    # answer_match_mean is still populated across all 3 turns
    assert agg["answer_match_mean"] is not None


def test_aggregate_recall_null_when_no_turn_has_gt():
    dataset = {
        "show_id": "show-1",
        "items": [
            _mk_item("t1", [_mk_turn("q1", None)]),
            _mk_item("t2", [_mk_turn("q2", None)]),
        ],
    }
    with patch.object(runner, "_search", side_effect=_stub_search_returning(["irrelevant"])), \
         patch.object(runner, "_query_chat_with_trace", side_effect=_stub_query_chat_with_trace), \
         patch.object(runner.Path, "read_text", return_value=__import__("json").dumps(dataset)):
        out = runner.run_eval(
            dataset_path=Path("ignored.json"),
            backend_url="http://x",
            auth_token="tok",
            top_k=5,
            label="test",
        )
    agg = out["aggregate"]
    assert agg["recall_at_k_mean"] is None
    assert agg["n_scored_recall"] == 0
    assert agg["answer_match_mean"] is not None  # other metrics still alive
