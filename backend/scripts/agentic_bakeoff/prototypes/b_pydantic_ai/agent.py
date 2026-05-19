"""Prototype B — Pydantic AI agent against AI Hub (< 250 LOC).

Mirror of prototype A contract:
  - same FrameworkAdapter protocol
  - same tools (registered from `tools` package)
  - same L0 (last K=3 turn pairs + rolling history_summary) + L1 (Redis state)
  - same MAIN_MODEL gemini-2.5-flash via OpenAIProvider -> AI Hub

Goal: see how much of A's hand-rolled loop / message-shape gluing the framework
abstracts away, and what trade-offs that comes with (debuggability, escape hatches).
"""
from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.services.ai_step_resolver import get_step_config

from ...runner.cost_latency_tracker import TurnTracker, usage_from_openai_response
from ...runner.metric_runner import ToolCallTrace, TurnResult
from ...state import ChatSessionState, load_state, save_state
from ...tools import TOOLS, TOOLS_BY_NAME, ToolSpec
from ...tools.context import ToolContext


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


@dataclass
class AgentDeps:
    """Passed to every tool via RunContext.deps."""
    ctx: ToolContext
    trace: list[str] = field(default_factory=list)
    tool_calls_trace: list[ToolCallTrace] = field(default_factory=list)


def _serialize(out: Any) -> Any:
    if isinstance(out, BaseModel):
        return json.loads(out.model_dump_json())
    return out


def _make_tool(spec: ToolSpec) -> Tool[AgentDeps]:
    """Build a Pydantic AI Tool that flattens input_model fields into kwargs."""
    Model = spec.input_model
    fields = Model.model_fields

    async def tool_fn(ctx_pai: RunContext[AgentDeps], **kwargs: Any) -> Any:
        try:
            inp = Model.model_validate(kwargs)
            if spec.is_async:
                out = await spec.callable(inp, ctx_pai.deps.ctx)
            else:
                out = spec.callable(inp, ctx_pai.deps.ctx)
            payload = _serialize(out)
            raised = None
        except Exception as e:
            payload = {"error": f"{type(e).__name__}: {e}"}
            raised = type(e).__name__
        ctx_pai.deps.tool_calls_trace.append(ToolCallTrace(
            name=spec.name,
            args=kwargs,
            result_summary=json.dumps(payload, ensure_ascii=False, default=str)[:120],
            raised=raised,
        ))
        ctx_pai.deps.trace.append(f"{spec.name}({json.dumps(kwargs, ensure_ascii=False)[:60]}) -> {str(payload)[:60]}")
        return payload

    params = [inspect.Parameter("ctx_pai", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=RunContext[AgentDeps])]
    annotations: dict[str, Any] = {"ctx_pai": RunContext[AgentDeps], "return": Any}
    for fname, fld in fields.items():
        default = inspect.Parameter.empty if fld.is_required() else fld.default
        params.append(inspect.Parameter(
            fname,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=fld.annotation,
            default=default,
        ))
        annotations[fname] = fld.annotation
    tool_fn.__signature__ = inspect.Signature(params)
    tool_fn.__annotations__ = annotations
    tool_fn.__name__ = spec.name
    tool_fn.__doc__ = spec.description
    return Tool(tool_fn, takes_ctx=True, name=spec.name, description=spec.description)


def _build_system_messages(state: ChatSessionState) -> list[str]:
    msgs = [SYSTEM_PROMPT]
    if state.history_summary:
        msgs.append(f"conversation_summary: {state.history_summary}")
    if state.focused_episode_id and state.focused_is_fresh():
        msgs.append(f"focused_episode_id: {state.focused_episode_id} (pinned, may be stale for unrelated topics)")
    return msgs


def _compress_history(
    client: OpenAI,
    prior_summary: str,
    last_user: str,
    last_answer: str,
    tracker: TurnTracker,
) -> str:
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
        return prior_summary


@dataclass
class PydanticAIAdapter:
    name: str = "b_pydantic_ai"
    _history: dict[str, list[ModelMessage]] = field(default_factory=dict)

    async def _build_agent(self, ctx: ToolContext, sys_msgs: list[str]) -> tuple[Agent[AgentDeps, str], OpenAI]:
        async with ctx.db_factory() as db:
            step = await get_step_config(db, "summary")
        provider = OpenAIProvider(base_url=step.base_url, api_key=step.api_key)
        model = OpenAIModel(MAIN_MODEL, provider=provider)
        tools = [_make_tool(t) for t in TOOLS]
        agent = Agent(
            model=model,
            deps_type=AgentDeps,
            tools=tools,
            system_prompt=tuple(sys_msgs),
            model_settings={"temperature": 0.0},
            retries=2,
        )
        compress_client = OpenAI(api_key=step.api_key, base_url=step.base_url)
        return agent, compress_client

    async def run_turn(
        self, question: str, session_id: str, ctx: ToolContext
    ) -> TurnResult:
        tracker = TurnTracker()
        deps = AgentDeps(ctx=ctx)
        state = load_state(ctx.redis_client, session_id, ctx.show_id)
        sys_msgs = _build_system_messages(state)

        agent, compress_client = await self._build_agent(ctx, sys_msgs)

        history = self._history.setdefault(session_id, [])
        recent = history[-(2 * K_LAST_TURNS):]

        final_answer = ""
        t0 = time.perf_counter()
        try:
            result = await agent.run(
                user_prompt=question,
                deps=deps,
                message_history=recent if recent else None,
            )
            wall_ms = (time.perf_counter() - t0) * 1000
            final_answer = (result.output if hasattr(result, "output") else result.data) or ""
            final_answer = final_answer.strip()
            usage = result.usage()
            tracker.record(MAIN_MODEL, usage.request_tokens or 0, usage.response_tokens or 0, wall_ms)
            history.extend(result.new_messages())
        except Exception as e:
            wall_ms = (time.perf_counter() - t0) * 1000
            tracker.record(MAIN_MODEL, 0, 0, wall_ms)
            final_answer = f"(pydantic_ai error: {type(e).__name__}: {e})"
            deps.trace.append(f"AGENT ERROR: {type(e).__name__}: {e}")

        state.history_summary = _compress_history(
            compress_client, state.history_summary, question, final_answer, tracker
        )
        save_state(ctx.redis_client, state)

        return TurnResult(
            answer=final_answer,
            tool_calls=deps.tool_calls_trace,
            wall_latency_ms=tracker.wall_latency_ms(),
            cost_usd=tracker.total_cost_usd,
            input_tokens=tracker.total_input_tokens,
            output_tokens=tracker.total_output_tokens,
            trace_log="\n".join(deps.trace),
        )

    async def reset_session(self, session_id: str) -> None:
        self._history.pop(session_id, None)
