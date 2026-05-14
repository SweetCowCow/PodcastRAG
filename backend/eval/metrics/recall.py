"""Recall@K — fraction of ground-truth chunks present in the top-K retrieved set.

Per the rag-eval-runner spec: items with empty ground_truth_chunk_ids
return None so the caller can exclude them from the average.
"""
from __future__ import annotations


def recall_at_k(
    top_chunks: list[str],
    ground_truth: list[str],
    k: int = 5,
) -> float | None:
    """Return |relevant ∩ topK| / |relevant|, or None if no ground-truth.

    Both lists hold canonical chunk_id strings (`ep:<uuid>@<start_time>`).
    Match is exact string equality.
    """
    if not ground_truth:
        return None
    topk = set(top_chunks[:k])
    relevant = set(ground_truth)
    return len(topk & relevant) / len(relevant)


def episode_set_recall(
    retrieved_episode_ids: list[str],
    expected_episode_ids: list[str],
) -> float | None:
    """Return |retrieved_eps ∩ expected_eps| / |expected_eps|.

    Used by `eval_mode == "enumeration"` items where retrieval is judged on
    catalog-wide episode coverage rather than chunk-level alignment. Range [0, 1].
    Returns None if `expected_episode_ids` is empty (callers SHOULD treat this as
    a schema violation upstream — enumeration items must declare a non-empty set).
    """
    if not expected_episode_ids:
        return None
    retrieved = set(retrieved_episode_ids)
    expected = set(expected_episode_ids)
    return len(retrieved & expected) / len(expected)
