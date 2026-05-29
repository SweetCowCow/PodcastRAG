"""context_entity_recall grader — DeepEval GEval custom rubric.

Entity-level retrieval coverage: identifies entities in the expected answer
summary (people / episode title / song / album / book / organisation), then
checks how many appear in the retrieved chunks.

DeepEval has no built-in equivalent — implemented as GEval. The score from
GEval already returns a [0,1] ratio close to `entities_found / entities_total`;
we expose it directly. The judge LLM articulates which entities were found /
missed in `details.reason`.

Inapplicable (returns None) when expected_answer_summary or retrieval_context
is empty.
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

_RUBRIC = (
    "From the expected answer summary, identify all distinct entities of these "
    "types: people (names), episode titles, song titles, album titles, book "
    "titles, organisations / brands.\n"
    "Then check the retrieval_context: for each entity, is it mentioned (by name "
    "or unambiguous reference) in at least one chunk?\n"
    "Return entities_found / entities_total as a score in [0, 1], rounded to 2 "
    "decimals. If the expected answer contains no entities, score 1.0.\n"
    "In the reasoning, list each entity with a found:true/false flag."
)


def grade(item: dict[str, Any], agent_response: dict[str, Any]) -> dict[str, Any] | None:
    scope = pick_scope(item)
    expected = scope.get("expected_answer_summary") or item.get("expected_answer_summary")
    retrieval_context = citations_to_retrieval_context(agent_response)
    if not expected or not retrieval_context:
        return None

    model = get_deepeval_model()
    if model is None:
        return make_error_result("no DeepEval API key configured")

    try:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        metric = GEval(
            name="ContextEntityRecall",
            criteria=_RUBRIC,
            evaluation_params=[
                LLMTestCaseParams.EXPECTED_OUTPUT,
                LLMTestCaseParams.RETRIEVAL_CONTEXT,
            ],
            threshold=PASS_THRESHOLD,
            model=model,
            async_mode=False,
        )
        # GEval reads expected_output + retrieval_context; input/actual_output unused
        # but LLMTestCase requires input + actual_output as non-empty strings.
        tc = LLMTestCase(
            input=scope.get("question") or item.get("question") or "(n/a)",
            actual_output=(agent_response or {}).get("answer") or "(n/a)",
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
