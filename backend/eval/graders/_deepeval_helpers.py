"""Shared helpers for DeepEval-based graders.

DeepEval defaults to api.openai.com. Our backend uses AI Hub (Zeabur) keys in
OPENAI_API_KEY env, which is not a real OpenAI endpoint — so grader code must
explicitly construct the LLM client with the right base_url.

Resolution order for the DeepEval LLM:
1. DEEPEVAL_OPENAI_API_KEY + DEEPEVAL_OPENAI_BASE_URL (explicit override)
2. OPENAI_API_KEY + OPENAI_BASE_URL (shared with backend)
3. OPENAI_API_KEY alone (DeepEval default base_url = api.openai.com)

Model defaults to gpt-4o-mini (cost-aware; override with DEEPEVAL_MODEL).
"""
from __future__ import annotations

import os
from typing import Any

# Filename starts with '_' so the grader loader skips this module.

DEFAULT_MODEL = "gpt-4o-mini"


def get_deepeval_model() -> Any | None:
    """Return a configured DeepEval GPTModel, or None if no API key is set.

    Returning None signals callers to short-circuit and report an error
    rather than letting DeepEval raise at metric init time.
    """
    api_key = os.getenv("DEEPEVAL_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("DEEPEVAL_OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    model_name = os.getenv("DEEPEVAL_MODEL", DEFAULT_MODEL)

    from deepeval.models.llms.openai_model import GPTModel

    kwargs: dict[str, Any] = {"model": model_name, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return GPTModel(**kwargs)


def citations_to_retrieval_context(agent_response: dict[str, Any]) -> list[str]:
    """Convert agent_response.citations (list of {episode_id,start_time,text,...})
    to a list of plain text chunks for DeepEval retrieval_context arg.
    """
    citations = (agent_response or {}).get("citations") or []
    out: list[str] = []
    for c in citations:
        text = c.get("text") or c.get("content") or ""
        if text:
            out.append(str(text))
    return out


def pick_scope(item: dict[str, Any]) -> dict[str, Any]:
    """For multi-turn items, scoring scope is the first turn (per existing
    grader convention in chunk_recall_grouped / answer_contradict_check).
    """
    if item.get("is_multi_turn"):
        turns = item.get("turns") or []
        if turns:
            return turns[0]
    return item


def make_error_result(msg: str) -> dict[str, Any]:
    return {"score": None, "passed": False, "details": {"error": msg[:300]}}
