"""Tests for the new `pronoun_attribution_check` indicator
(change: judge-pronoun-attribution-check).

Stub-client tests — exercise the parse / fallback / null-default logic for the
new fourth top-level key. Real LLM-judge calibration happens in Phase 3 against
prod, not here.
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.eval.judge_chat_v2 import (
    build_payload,
    invoke_judge,
)


class _StubClient:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0
        outer = self

        class _Completions:
            def create(self_inner, **kwargs):  # noqa: ARG002
                outer.calls += 1
                content = outer._responses.pop(0)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
                )

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _judge_resp(pronoun_verdict: str | None) -> str:
    """Build a JSON response with optional pronoun_attribution_check verdict."""
    parts = [
        '"factual_correctness": {"score": 0.5, "rationale": "ok"}',
        '"refusal_appropriateness": {"verdict": "appropriate", "is_refusal_with_correction": false, "rationale": "ok"}',
        '"answer_contradict_check": null',
    ]
    if pronoun_verdict is None:
        parts.append('"pronoun_attribution_check": null')
    else:
        parts.append(
            f'"pronoun_attribution_check": {{"verdict": "{pronoun_verdict}", "rationale": "stub"}}'
        )
    return "{" + ", ".join(parts) + "}"


def test_pronoun_attribution_verdict_grounded_parsed():
    """Spec scenario «judge returns four structured verdicts in a single call»
    — grounded path."""
    client = _StubClient([_judge_resp("grounded")])
    out = invoke_judge({"question": "Q"}, client=client, model="stub-model")
    assert out["pronoun_attribution_check"]["verdict"] == "grounded"


def test_pronoun_attribution_verdict_inferred_parsed():
    """Spec scenario «accepts legitimate pronoun inference» — inferred path."""
    client = _StubClient([_judge_resp("inferred")])
    out = invoke_judge({"question": "Q"}, client=client, model="stub-model")
    assert out["pronoun_attribution_check"]["verdict"] == "inferred"


def test_pronoun_attribution_verdict_hallucinated_parsed():
    """Spec scenario «detects hallucinated person attribution» — hallucinated
    path. Exercised against the b23-shaped stub response so the contract holds
    for the case the change was opened to fix."""
    client = _StubClient([_judge_resp("hallucinated")])
    out = invoke_judge({"question": "Q"}, client=client, model="stub-model")
    assert out["pronoun_attribution_check"]["verdict"] == "hallucinated"
    assert "stub" in out["pronoun_attribution_check"]["rationale"]


def test_pronoun_attribution_null_when_not_applicable():
    """Spec scenario «pronoun_attribution_check is null when ... does not
    involve multi-person attribution»."""
    client = _StubClient([_judge_resp(None)])
    out = invoke_judge({"question": "Q"}, client=client, model="stub-model")
    assert out["pronoun_attribution_check"] is None


def test_build_payload_omits_result_summary_key():
    """`build_payload` SHALL emit `result_full` (NOT legacy `result_summary`)
    so the prompt's tool_calls section is wire-compatible with the new rubric.
    """
    item = {"id": "x", "question": "Q?", "expected_answer_summary": "S"}
    resp = {
        "answer": "A",
        "tool_calls": [
            {"name": "search", "args": {"q": "x"}, "result_full": "chunk text"}
        ],
    }
    payload = build_payload(item, resp)
    tc = payload["tool_calls"][0]
    assert "result_full" in tc
    assert tc["result_full"] == "chunk text"
    assert "result_summary" not in tc
