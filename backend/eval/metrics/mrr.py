"""MRR — reciprocal rank of the first relevant chunk in the retrieved list.

Per the rag-eval-runner spec: rank is 1-based; if no relevant chunk appears
this item contributes 0 to the mean.
"""
from __future__ import annotations


def reciprocal_rank(top_chunks: list[str], ground_truth: list[str]) -> float:
    """Return 1/rank for the first ground-truth hit, or 0 if none.

    Both lists hold canonical chunk_id strings; match is exact string equality.
    """
    relevant = set(ground_truth)
    if not relevant:
        return 0.0
    for idx, chunk_id in enumerate(top_chunks):
        if chunk_id in relevant:
            return 1.0 / (idx + 1)
    return 0.0


def mrr(retrieved_per_query: list[list[str]], ground_truth_per_query: list[list[str]]) -> float:
    """Mean reciprocal rank across a list of queries."""
    if len(retrieved_per_query) != len(ground_truth_per_query):
        raise ValueError("mismatched lengths")
    if not retrieved_per_query:
        return 0.0
    return sum(
        reciprocal_rank(r, g) for r, g in zip(retrieved_per_query, ground_truth_per_query)
    ) / len(retrieved_per_query)
