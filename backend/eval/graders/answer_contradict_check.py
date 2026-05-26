"""answer_contradict_check grader.

Reads the LLM judge's `answer_contradict_check` field. The runner is expected to
invoke the chat-rag judge ONCE per item and stash the parsed JSON under
agent_response['_judge_verdict']; this grader is a thin reader so we don't
triple-charge LLM budget (per design D3 / acceptance criterion #1).

Returns None when the item carries no expected_must_contradict_check directive.
"""
from __future__ import annotations

from typing import Any


def grade(item: dict[str, Any], agent_response: dict[str, Any]) -> dict[str, Any] | None:
    scope = item
    if item.get("is_multi_turn"):
        turns = item.get("turns") or []
        if turns:
            scope = turns[0]

    directive = scope.get("expected_must_contradict_check") or item.get(
        "expected_must_contradict_check"
    )
    if not directive:
        return None

    verdict = ((agent_response or {}).get("_judge_verdict") or {}).get(
        "answer_contradict_check"
    )
    if verdict is None:
        return {
            "score": 0.0,
            "passed": False,
            "details": {"error": "judge did not populate answer_contradict_check"},
        }
    if verdict.get("_error"):
        return {
            "score": None,
            "passed": False,
            "details": {"error": verdict.get("rationale", "judge error")},
        }

    passed = bool(verdict.get("passed"))
    return {
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "details": {"judge_rationale": verdict.get("rationale")},
    }
