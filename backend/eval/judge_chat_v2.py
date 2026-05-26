"""chat-rag v2 LLM judge wrapper.

Single LLM call returns three structured verdicts:
- factual_correctness {score, rationale}
- refusal_appropriateness {verdict, is_refusal_with_correction, rationale}
- answer_contradict_check {passed, rationale} | null

Reads prompt from backend/eval/prompts/chat_judge_v2.md (cache-friendly prefix).
Truncates tool result_full to 800 chars before sending to judge (see design D4).
1 retry on malformed JSON; persistent failure → marks all three as "error".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from backend.eval.judge_config import JUDGE_PROVIDER_BASE_URL, PRODUCTION_JUDGE_MODEL

PROMPT_PATH = Path(__file__).parent / "prompts" / "chat_judge_v2.md"
RESULT_TRUNCATE_CHARS = 800


def load_prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_prompt_sha256() -> str:
    return hashlib.sha256(load_prompt_text().encode("utf-8")).hexdigest()


def _truncate_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        s = result
    else:
        try:
            s = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            s = str(result)
    if len(s) > RESULT_TRUNCATE_CHARS:
        return s[:RESULT_TRUNCATE_CHARS] + "[truncated]"
    return s


def build_payload(
    item: dict[str, Any],
    agent_response: dict[str, Any],
    *,
    turn_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON input payload for the judge.

    turn_scope is the per-turn slice for multi-turn items; falls back to item itself.
    """
    scope = turn_scope or item
    tool_calls = []
    for tc in (agent_response or {}).get("tool_calls") or []:
        result = tc.get("result_full") or tc.get("result")
        tool_calls.append(
            {
                "name": tc.get("name"),
                "args": tc.get("args"),
                "result_summary": _truncate_result(result),
            }
        )

    return {
        "question": scope.get("question") or item.get("question") or "",
        "expected_answer_summary": scope.get("expected_answer_summary")
        or item.get("expected_answer_summary")
        or "",
        "expected_answer_aliases": scope.get("expected_answer_aliases")
        or item.get("expected_answer_aliases"),
        "expected_must_contradict_check": scope.get("expected_must_contradict_check")
        or item.get("expected_must_contradict_check"),
        "expected_behavior": scope.get("expected_behavior")
        or item.get("expected_behavior")
        or "answer",
        "agent_answer": (agent_response or {}).get("answer") or "",
        "tool_calls": tool_calls,
    }


def _extract_json(raw: str) -> dict:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return json.loads(s)


def _error_envelope(msg: str) -> dict[str, Any]:
    return {
        "factual_correctness": {"score": None, "rationale": f"error: {msg}", "_error": True},
        "refusal_appropriateness": {
            "verdict": "error",
            "is_refusal_with_correction": False,
            "rationale": f"error: {msg}",
            "_error": True,
        },
        "answer_contradict_check": {"passed": False, "rationale": f"error: {msg}", "_error": True},
    }


def _make_client() -> OpenAI:
    api_key = os.environ.get("AIHUB_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("AIHUB_API_KEY / OPENAI_API_KEY not set")
    return OpenAI(api_key=api_key, base_url=JUDGE_PROVIDER_BASE_URL)


def invoke_judge(
    payload: dict[str, Any],
    *,
    model: str | None = None,
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """Invoke judge, return parsed JSON with three top-level keys. 1 retry on malformed."""
    use_model = model or PRODUCTION_JUDGE_MODEL
    use_client = client or _make_client()
    prompt = load_prompt_text()

    def _call_once() -> str:
        resp = use_client.chat.completions.create(
            model=use_model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""

    last_err: Exception | None = None
    for _attempt in range(2):
        try:
            raw = _call_once()
            parsed = _extract_json(raw)
            if not isinstance(parsed, dict):
                raise ValueError("judge returned non-dict")
            for key in ("factual_correctness", "refusal_appropriateness"):
                if key not in parsed:
                    raise ValueError(f"missing key {key}")
            # answer_contradict_check is optional/null
            if "answer_contradict_check" not in parsed:
                parsed["answer_contradict_check"] = None
            return parsed
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            last_err = e
            continue
        except Exception as e:  # network / OpenAI exceptions
            last_err = e
            break

    return _error_envelope(str(last_err)[:200] if last_err else "unknown")
