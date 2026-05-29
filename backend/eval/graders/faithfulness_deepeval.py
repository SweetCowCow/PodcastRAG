"""faithfulness_deepeval grader — wrap DeepEval FaithfulnessMetric.

Measures whether the agent's actual answer is grounded in (faithful to) the
retrieved chunks — i.e. does NOT contradict or fabricate beyond retrieval_context.
Score in [0, 1]; pass threshold = 0.7.

Module name uses `_deepeval` suffix to avoid collision with the existing
self-written `factual_correctness` grader (which checks against GT, not retrieval).

Inapplicable (returns None) when agent has no answer or retrieval_context is empty.
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
    answer = (agent_response or {}).get("answer")
    retrieval_context = citations_to_retrieval_context(agent_response)
    if not question or not answer or not retrieval_context:
        return None

    model = get_deepeval_model()
    if model is None:
        return make_error_result("no DeepEval API key configured")

    try:
        from deepeval.metrics import FaithfulnessMetric
        from deepeval.test_case import LLMTestCase

        metric = FaithfulnessMetric(threshold=PASS_THRESHOLD, model=model, async_mode=False)
        tc = LLMTestCase(
            input=str(question),
            actual_output=str(answer),
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
