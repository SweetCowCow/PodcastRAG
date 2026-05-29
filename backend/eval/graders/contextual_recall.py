"""contextual_recall grader — wrap DeepEval ContextualRecallMetric.

Measures whether retrieved chunks (retrieval_context) collectively cover the
information needed to produce the expected answer. Score in [0, 1]; pass
threshold = 0.7.

Complements existing `chunk_recall_grouped` which uses strict chunk-ID + 10s
window matching: this metric uses LLM semantic comparison, catching cases where
retrieval picked up the right content but chunk boundaries drifted.

Inapplicable (returns None) when item has no expected_answer_summary or
agent's retrieval_context is empty.
"""
from __future__ import annotations

from typing import Any

from ._deepeval_helpers import (
    citations_to_retrieval_context,
    get_deepeval_model,
    make_error_result,
    pick_scope,
)

PASS_THRESHOLD = 0.7


def grade(item: dict[str, Any], agent_response: dict[str, Any]) -> dict[str, Any] | None:
    scope = pick_scope(item)
    question = scope.get("question") or item.get("question")
    expected = scope.get("expected_answer_summary") or item.get("expected_answer_summary")
    answer = (agent_response or {}).get("answer")
    retrieval_context = citations_to_retrieval_context(agent_response)
    if not question or not expected or not retrieval_context or not answer:
        return None

    model = get_deepeval_model()
    if model is None:
        return make_error_result("no DeepEval API key configured")

    try:
        from deepeval.metrics import ContextualRecallMetric
        from deepeval.test_case import LLMTestCase

        metric = ContextualRecallMetric(threshold=PASS_THRESHOLD, model=model, async_mode=False)
        tc = LLMTestCase(
            input=str(question),
            actual_output=str(answer),
            expected_output=str(expected),
            retrieval_context=retrieval_context,
        )
        metric.measure(tc)
        score = float(metric.score) if metric.score is not None else None
        return {
            "score": score,
            "passed": bool(score is not None and score >= PASS_THRESHOLD),
            "details": {"reason": getattr(metric, "reason", None)},
        }
    except Exception as e:  # noqa: BLE001
        return make_error_result(f"{type(e).__name__}: {e}")
