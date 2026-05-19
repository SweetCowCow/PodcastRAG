"""Prototype A — native OpenAI tool calling against AI Hub (< 250 LOC).

Implements the FrameworkAdapter protocol from runner/metric_runner.py.

Loop sketch:
  user_question -> build_messages(system + summary + last_K + user)
                -> openai.chat.completions.create(tools=...)
                -> while resp has tool_calls:
                     dispatch each via TOOLS_BY_NAME -> append tool result msg
                     re-call openai
                -> compress L0 history_summary (gemini-2.5-flash-lite, fail-open)
                -> return TurnResult(answer, tool_calls, latency, cost, trace)

L0 memory: last K=3 user/assistant turns kept verbatim + rolling history_summary
            (compressed every turn).
L1 memory: ChatSessionState (Redis 2h TTL) — written by pin/unpin tools, read
           by agent at turn start (for context awareness only; agent decides
           via prompt + tool docs whether to honor `focused_episode_id`).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
import uuid
from dataclasses import dataclass, field

from openai import OpenAI
from pydantic import BaseModel

from app.services.ai_step_resolver import get_step_config

from ..runner_models import import_for_adapter  # noqa: F401 (registers protocol)
from ...runner.cost_latency_tracker import TurnTracker, usage_from_openai_response
from ...runner.metric_runner import ToolCallTrace, TurnResult
from ...state import ChatSessionState, load_state, save_state
from ...tools import TOOLS, TOOLS_BY_NAME, ToolSpec
from ...tools.context import ToolContext


# Bake-off fixes the chat model per design.md Decision (gemini-2.5-flash).
# api_key + base_url are pulled from ai_steps (same pattern as prod chat) —
# avoids env var key mismatch between local and prod container.
MAIN_MODEL = "gemini-2.5-flash"
SUMMARY_MODEL = "gemini-2.5-flash-lite"
K_LAST_TURNS = 3
HISTORY_SUMMARY_MAX_CHARS = 300
MAX_TOOL_ITERATIONS = 8

SYSTEM_PROMPT = """你是 PodcastRAG 的 chat agent，使用 tool calling 回答關於 podcast 的問題。
- 拿到問題時先想：要呼哪些 tool？多步驟可以分段呼叫。
- 對於 multi-turn 對話，注意 conversation_summary 與 focused_episode_id（pin 過的某集），但若新問題跟 focused episode 無關，請主動跳出（必要時 unpin）。
- 找不到資料時直接說「節目未提及」，不要 hallucinate。
- 答案盡量簡短，引用具體 EP 編號。"""


def _pydantic_to_openai_function(spec: ToolSpec) -> dict:
    schema = spec.input_model.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": schema,
        },
    }


OPENAI_TOOLS_SPEC = [_pydantic_to_openai_function(t) for t in TOOLS]


def _build_messages(
    state: ChatSessionState,
    history: list[dict],
    user_question: str,
) -> list[dict]:
    msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if state.history_summary:
        msgs.append({"role": "system", "content": f"conversation_summary: {state.history_summary}"})
    if state.focused_episode_id and state.focused_is_fresh():
        msgs.append({"role": "system", "content": f"focused_episode_id: {state.focused_episode_id} (pinned, may be stale for unrelated topics)"})
    # last K turns from history (in chronological order)
    msgs.extend(history[-(2 * K_LAST_TURNS):])
    msgs.append({"role": "user", "content": user_question})
    return msgs


async def _dispatch_tool(
    spec: ToolSpec,
    args_json: str,
    ctx: ToolContext,
) -> tuple[str, str | None]:
    """Run a tool; return (result_json_str, exception_class_name_or_None)."""
    try:
        args = json.loads(args_json or "{}")
        inp = spec.input_model.model_validate(args)
        if spec.is_async:
            out = await spec.callable(inp, ctx)
        else:
            out = spec.callable(inp, ctx)
        if isinstance(out, BaseModel):
            return (out.model_dump_json(), None)
        return (json.dumps(out, ensure_ascii=False, default=str), None)
    except Exception as e:
        return (
            json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False),
            type(e).__name__,
        )


def _compress_history(
    client: OpenAI,
    prior_summary: str,
    last_user: str,
    last_answer: str,
    tracker: TurnTracker,
) -> str:
    """Incremental history_summary compression. Fail-open."""
    try:
        prompt = (
            f"舊摘要: {prior_summary or '(空)'}\n\n"
            f"User: {last_user}\nAssistant: {last_answer}\n\n"
            f"用 <= {HISTORY_SUMMARY_MAX_CHARS} 字概述對話脈絡（focused 集、已 enumerate 過的列表、user 偏好）。"
        )
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=SUMMARY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        inp_t, out_t = usage_from_openai_response(resp)
        tracker.record(SUMMARY_MODEL, inp_t, out_t, latency_ms)
        return (resp.choices[0].message.content or "").strip()[:HISTORY_SUMMARY_MAX_CHARS]
    except Exception:
        return prior_summary  # fail-open: keep prior


@dataclass
class NativeOpenAIAdapter:
    """FrameworkAdapter implementation."""
    name: str = "a_native_openai"
    # per-session message history (last K turns), keyed by session_id
    _history: dict[str, list[dict]] = field(default_factory=dict)

    async def _client(self, ctx: ToolContext) -> OpenAI:
        # Pull AI Hub creds from ai_steps.summary (any chat step works; summary
        # already lives on AI Hub gemini in prod per CLAUDE.md).
        async with ctx.db_factory() as db:
            step = await get_step_config(db, "summary")
        return OpenAI(api_key=step.api_key, base_url=step.base_url)

    async def run_turn(
        self, question: str, session_id: str, ctx: ToolContext
    ) -> TurnResult:
        client = await self._client(ctx)
        tracker = TurnTracker()
        trace: list[str] = []
        tool_calls_trace: list[ToolCallTrace] = []

        state = load_state(ctx.redis_client, session_id, ctx.show_id)
        history = self._history.setdefault(session_id, [])
        messages = _build_messages(state, history, question)

        final_answer = ""
        for it in range(MAX_TOOL_ITERATIONS):
            t0 = time.perf_counter()
            resp = client.chat.completions.create(
                model=MAIN_MODEL,
                messages=messages,
                tools=OPENAI_TOOLS_SPEC,
                temperature=0.0,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            inp_t, out_t = usage_from_openai_response(resp)
            tracker.record(MAIN_MODEL, inp_t, out_t, latency_ms)

            choice = resp.choices[0]
            msg = choice.message
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls:
                final_answer = (msg.content or "").strip()
                trace.append(f"[iter {it}] final answer ({len(final_answer)} chars)")
                break

            # append assistant message with tool_calls (required by OpenAI protocol)
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })

            # dispatch each tool call
            for tc in tool_calls:
                tname = tc.function.name
                spec = TOOLS_BY_NAME.get(tname)
                if spec is None:
                    result_str = json.dumps({"error": f"unknown tool: {tname}"})
                    raised_name = "UnknownTool"
                else:
                    result_str, raised_name = await _dispatch_tool(
                        spec, tc.function.arguments, ctx
                    )
                tool_calls_trace.append(ToolCallTrace(
                    name=tname,
                    args=_safe_parse_json(tc.function.arguments),
                    result_summary=result_str[:120],
                    raised=raised_name,
                ))
                trace.append(f"[iter {it}] {tname}({tc.function.arguments[:60]}) -> {result_str[:60]}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })
        else:
            final_answer = "(reached MAX_TOOL_ITERATIONS without final answer)"
            trace.append(f"hit MAX_TOOL_ITERATIONS={MAX_TOOL_ITERATIONS}")

        # update L0 history
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": final_answer})

        # compress L0 summary (fail-open)
        state.history_summary = _compress_history(
            client, state.history_summary, question, final_answer, tracker
        )
        save_state(ctx.redis_client, state)

        return TurnResult(
            answer=final_answer,
            tool_calls=tool_calls_trace,
            wall_latency_ms=tracker.wall_latency_ms(),
            cost_usd=tracker.total_cost_usd,
            input_tokens=tracker.total_input_tokens,
            output_tokens=tracker.total_output_tokens,
            trace_log="\n".join(trace),
        )

    async def reset_session(self, session_id: str) -> None:
        self._history.pop(session_id, None)


def _safe_parse_json(s: str) -> dict:
    try:
        return json.loads(s or "{}")
    except Exception:
        return {"_raw": (s or "")[:100]}
