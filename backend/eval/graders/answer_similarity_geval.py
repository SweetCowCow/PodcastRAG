"""answer_similarity_geval grader — DeepEval GEval custom rubric.

Compares agent's actual answer against the expected answer summary on three axes:
- Content coverage: does the actual answer cover the key points of the expected?
- Factual consistency: does the actual answer contradict the expected?
- No unsupported additions: does the actual answer add claims beyond the expected?

DeepEval has no built-in AnswerSimilarityMetric class (verified 2026-05-29);
this GEval rubric replaces the original spec intent.

Inapplicable (returns None) when item has no expected_answer_summary or
agent has no answer.
"""
from __future__ import annotations

from typing import Any

from ._deepeval_helpers import (
    get_deepeval_model,
    make_error_result,
    pick_scope,
)

PASS_THRESHOLD = 0.7

_RUBRIC = (
    "Compare the agent's actual answer against the expected answer summary.\n"
    "Score the actual answer on three axes, each contributing equally:\n"
    "1. Content coverage — does the actual answer cover the key points of the expected?\n"
    "2. Factual consistency — does the actual answer contradict any facts in the expected?\n"
    "3. No unsupported additions — does the actual answer fabricate claims absent from the expected?\n"
    "Return a single score in [0, 1] where 1.0 = perfect on all three axes."
)


def grade(item: dict[str, Any], agent_response: dict[str, Any]) -> dict[str, Any] | None:
    scope = pick_scope(item)
    question = scope.get("question") or item.get("question")
    expected = scope.get("expected_answer_summary") or item.get("expected_answer_summary")
    answer = (agent_response or {}).get("answer")
    if not question or not expected or not answer:
        return None

    model = get_deepeval_model()
    if model is None:
        return make_error_result("no DeepEval API key configured")

    try:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        metric = GEval(
            name="AnswerSimilarity",
            criteria=_RUBRIC,
            evaluation_params=[
                LLMTestCaseParams.INPUT,
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            threshold=PASS_THRESHOLD,
            model=model,
            async_mode=False,
        )
        tc = LLMTestCase(
            input=str(question),
            actual_output=str(answer),
            expected_output=str(expected),
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
