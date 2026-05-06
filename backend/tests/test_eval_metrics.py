"""Unit tests for Recall@K and MRR.

Cases derived from the rag-eval-runner spec scenarios + example table.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# backend/eval is a sibling of backend/app; add the backend root to sys.path so
# we can `import eval` without collisions (the test runs with cwd=backend/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.metrics.recall import recall_at_k  # noqa: E402
from eval.metrics.mrr import mrr, reciprocal_rank  # noqa: E402


# ────────────────────────────────────────────────────────────────────
# Recall@K
# ────────────────────────────────────────────────────────────────────

def test_recall_one_of_two_ground_truth_in_top5():
    """Spec scenario: one of two relevant chunks appears in top-5."""
    top5 = ["ep:c@0.50", "ep:a@1.00", "ep:d@3.00", "ep:e@4.00", "ep:f@5.00"]
    gt = ["ep:a@1.00", "ep:b@2.00"]
    assert recall_at_k(top5, gt, k=5) == 0.5


def test_recall_empty_ground_truth_returns_none():
    """Spec scenario: negative items have empty ground-truth → excluded."""
    assert recall_at_k(["ep:a@1.00"], [], k=5) is None


def test_recall_full_hit():
    top5 = ["ep:a@1.00", "ep:b@2.00", "ep:c@3.00", "ep:d@4.00", "ep:e@5.00"]
    gt = ["ep:a@1.00", "ep:b@2.00"]
    assert recall_at_k(top5, gt, k=5) == 1.0


def test_recall_k_truncates():
    top10 = [f"ep:a@{i}.00" for i in range(10)]
    gt = ["ep:a@8.00"]
    assert recall_at_k(top10, gt, k=5) == 0.0
    assert recall_at_k(top10, gt, k=10) == 1.0


# Spec example table (3-item recall computation):
# q1 → 1.0, q2 → 0.5, q3 negative → excluded → mean over q1,q2 = 0.75
def test_recall_example_table_three_item_average():
    cases = [
        # (top5, gt, expected_per_item)
        (["ep:a@1.00"] + ["ep:x@9.00"] * 4, ["ep:a@1.00"], 1.0),
        (["ep:x@9.00", "ep:b@2.00"] + ["ep:y@9.00"] * 3, ["ep:b@2.00", "ep:c@3.00"], 0.5),
        (["ep:x@9.00"] * 5, [], None),
    ]
    per_item = [recall_at_k(t, g, k=5) for t, g, _ in cases]
    assert per_item == [1.0, 0.5, None]
    real = [v for v in per_item if v is not None]
    assert sum(real) / len(real) == 0.75


# ────────────────────────────────────────────────────────────────────
# MRR
# ────────────────────────────────────────────────────────────────────

def test_reciprocal_rank_first_hit_at_index_1_is_half():
    """Spec scenario: first relevant chunk at rank 2 (index 1) → 0.5."""
    top = ["ep:x@9.00", "ep:a@1.00", "ep:y@9.00"]
    gt = ["ep:a@1.00"]
    assert reciprocal_rank(top, gt) == 0.5


def test_reciprocal_rank_no_hit_is_zero():
    assert reciprocal_rank(["ep:x@9.00"] * 5, ["ep:a@1.00"]) == 0.0


def test_reciprocal_rank_first_position_is_one():
    assert reciprocal_rank(["ep:a@1.00", "ep:b@2.00"], ["ep:a@1.00"]) == 1.0


def test_mrr_single_item_set():
    """Single-item set, first relevant at rank 2 → MRR = 0.5."""
    assert mrr([["ep:x@9.00", "ep:a@1.00"]], [["ep:a@1.00"]]) == 0.5


def test_mrr_mixed_set():
    retrieved = [
        ["ep:a@1.00"],                      # hit at rank 1 → 1.0
        ["ep:x@9.00", "ep:b@2.00"],         # hit at rank 2 → 0.5
        ["ep:x@9.00"],                      # no hit → 0
    ]
    gt = [["ep:a@1.00"], ["ep:b@2.00"], ["ep:c@3.00"]]
    # mean(1.0, 0.5, 0.0) = 0.5
    assert mrr(retrieved, gt) == 0.5


def test_mrr_empty_returns_zero():
    assert mrr([], []) == 0.0
