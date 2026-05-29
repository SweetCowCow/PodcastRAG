"""answer_relevancy grader — wrap DeepEval AnswerRelevancyMetric.

Measures how relevant the agent's answer is to the input question.
Score in [0, 1]; pass threshold = 0.7 (DeepEval default).

Inapplicable (returns None) when item has no question or agent has no answer.
LLM failures return {score: null, passed: false, details: {error: ...}}.
"""
from __future__ import annotations

from typing import Any

from ._deepeval_helpers import (
    get_deepeval_model,
    make_error_result,
    pick_scope,
)

PASS_THRESHOLD = 0.7


def grade(item: dict[str, Any], agent_response: dict[str, Any]) -> dict[str, Any] | None:
    scope = pick_scope(item)
    question = scope.get("question") or item.get("question")
    answer = (agent_response or {}).get("answer")
    if not question or not answer:
        return None

    model = get_deepeval_model()
    if model is None:
        return make_error_result("no DeepEval API key configured")

    try:
        from deepeval.metrics import AnswerRelevancyMetric
        from deepeval.test_case import LLMTestCase

        metric = AnswerRelevancyMetric(threshold=PASS_THRESHOLD, model=model, async_mode=False)
        tc = LLMTestCase(input=str(question), actual_output=str(answer))
        metric.measure(tc)
        score = float(metric.score) if metric.score is not None else None
        return {
            "score": score,
            "passed": bool(score is not None and score >= PASS_THRESHOLD),
            "details": {"reason": getattr(metric, "reason", None)},
        }
    except Exception as e:  # noqa: BLE001
        return make_error_result(f"{type(e).__name__}: {e}")
