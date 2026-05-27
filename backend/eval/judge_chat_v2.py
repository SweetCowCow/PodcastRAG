"""chat-rag v2 LLM judge wrapper.

Single LLM call returns four structured verdicts:
- factual_correctness {score, rationale}
- refusal_appropriateness {verdict, is_refusal_with_correction, rationale}
- answer_contradict_check {passed, rationale} | null
- pronoun_attribution_check {verdict, rationale} | null

Reads prompt from backend/eval/prompts/chat_judge_v2.md (cache-friendly prefix).
Truncates tool result_full to `RESULT_FULL_CAP_CHARS` (matches the agent loop's
`agentic_tool_result_max_chars`) before sending to judge so the judge sees the
same payload window the agent LLM saw — required for pronoun-attribution
verification per change `judge-pronoun-attribution-check`.
1 retry on malformed JSON; persistent failure → marks all four as "error".
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
# Cap matches agent loop `settings.agentic_tool_result_max_chars` (8000) so the
# judge sees the same content the agent LLM saw when generating the answer.
RESULT_FULL_CAP_CHARS = 8000


def load_prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_prompt_sha256() -> str:
    return hashlib.sha256(load_prompt_text().encode("utf-8")).hexdigest()


def _coerce_to_str(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


def _cap_result_full(result: Any) -> str:
    """Cap tool result to `RESULT_FULL_CAP_CHARS`, preserving the agent loop's
    truncation suffix shape when capping is triggered.
    """
    s = _coerce_to_str(result)
    if len(s) > RESULT_FULL_CAP_CHARS:
        omitted = len(s) - RESULT_FULL_CAP_CHARS
        return f"{s[:RESULT_FULL_CAP_CHARS]}... (truncated, {omitted} chars omitted)"
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
                "result_full": _cap_result_full(result),
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
        "pronoun_attribution_check": {
            "verdict": "error",
            "rationale": f"error: {msg}",
            "_error": True,
        },
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
            # pronoun_attribution_check is optional/null
            if "pronoun_attribution_check" not in parsed:
                parsed["pronoun_attribution_check"] = None
            return parsed
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            last_err = e
            continue
        except Exception as e:  # network / OpenAI exceptions
            last_err = e
            break

    return _error_envelope(str(last_err)[:200] if last_err else "unknown")
