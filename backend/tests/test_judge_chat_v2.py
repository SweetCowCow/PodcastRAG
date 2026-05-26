"""Tests for chat_judge_v2 wrapper.

Uses a stub OpenAI client (no network) to avoid LLM cost.
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.eval.judge_chat_v2 import (
    RESULT_TRUNCATE_CHARS,
    _extract_json,
    build_payload,
    invoke_judge,
    load_prompt_sha256,
    load_prompt_text,
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


def test_build_payload_truncates_tool_result():
    item = {
        "id": "b14",
        "question": "Q?",
        "expected_answer_summary": "S",
        "expected_must_contradict_check": "X",
    }
    long = "x" * 5000
    resp = {
        "answer": "A",
        "tool_calls": [{"name": "t", "args": {"a": 1}, "result_full": long}],
    }
    payload = build_payload(item, resp)
    summary = payload["tool_calls"][0]["result_summary"]
    assert len(summary) <= RESULT_TRUNCATE_CHARS + len("[truncated]")
    assert summary.endswith("[truncated]")
    assert payload["expected_must_contradict_check"] == "X"


def test_invoke_judge_happy_path_three_keys():
    good = (
        '{"factual_correctness": {"score": 1.0, "rationale": "ok"},'
        ' "refusal_appropriateness": {"verdict": "appropriate", "is_refusal_with_correction": false, "rationale": "ok"},'
        ' "answer_contradict_check": null}'
    )
    client = _StubClient([good])
    out = invoke_judge({"question": "Q"}, client=client, model="stub-model")
    assert client.calls == 1
    assert out["factual_correctness"]["score"] == 1.0
    assert out["refusal_appropriateness"]["verdict"] == "appropriate"
    assert out["answer_contradict_check"] is None


def test_invoke_judge_retries_once_then_errors():
    client = _StubClient(["not json", "still not json"])
    out = invoke_judge({"question": "Q"}, client=client, model="stub-model")
    assert client.calls == 2
    assert out["factual_correctness"].get("_error") is True
    assert out["refusal_appropriateness"]["verdict"] == "error"


def test_invoke_judge_recovers_on_retry():
    good = (
        '{"factual_correctness": {"score": 0.5, "rationale": "ok"},'
        ' "refusal_appropriateness": {"verdict": "appropriate", "is_refusal_with_correction": false, "rationale": "ok"}}'
    )
    client = _StubClient(["not json", good])
    out = invoke_judge({"question": "Q"}, client=client, model="stub-model")
    assert client.calls == 2
    assert out["factual_correctness"]["score"] == 0.5
    # Missing answer_contradict_check defaults to null
    assert out["answer_contradict_check"] is None


def test_prompt_loads_and_sha256_stable():
    sha1 = load_prompt_sha256()
    sha2 = load_prompt_sha256()
    assert sha1 == sha2
    assert len(sha1) == 64
    assert "迪拉胖在 EP134" in load_prompt_text()


def test_extract_json_strips_fences():
    raw = '```json\n{"a":1}\n```'
    assert _extract_json(raw) == {"a": 1}
