"""Prototype E — Google ADK (LlmAgent + LiteLlm AI Hub adapter, < 250 LOC).

Mirror of prototype A / B contract:
  - same FrameworkAdapter protocol
  - same tools (registered from `tools` package, flattened signatures)
  - same L0 (last K=3 turn pairs via ADK InMemorySessionService) +
    L1 (Redis ChatSessionState)
  - same MAIN_MODEL gemini-2.5-flash via LiteLlm("openai/gemini-2.5-flash")

NOT installed by main Dockerfile — see requirements-bakeoff.txt header.
Bake-off runner must `pip install -r requirements-bakeoff.txt` first.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from types import UnionType
from typing import Any, Union, get_args, get_origin

from openai import OpenAI
from pydantic import BaseModel

from app.services.ai_step_resolver import get_step_config

from ...runner.cost_latency_tracker import TurnTracker, usage_from_openai_response
from ...runner.metric_runner import ToolCallTrace, TurnResult
from ...state import ChatSessionState, load_state, save_state
from ...tools import TOOLS, ToolSpec
from ...tools.context import ToolContext


MAIN_MODEL = "gemini-2.5-flash"
SUMMARY_MODEL = "gemini-2.5-flash-lite"
APP_NAME = "agentic_bakeoff_e"
K_LAST_TURNS = 3
HISTORY_SUMMARY_MAX_CHARS = 300

SYSTEM_PROMPT = """你是 PodcastRAG 的 chat agent，使用 tool calling 回答關於 podcast 的問題。
- 拿到問題時先想：要呼哪些 tool？多步驟可以分段呼叫。
- 對於 multi-turn 對話，注意 conversation_summary 與 focused_episode_id（pin 過的某集），但若新問題跟 focused episode 無關，請主動跳出（必要時 unpin）。
- 找不到資料時直接說「節目未提及」，不要 hallucinate。
- 答案盡量簡短，引用具體 EP 編號。"""


def _serialize(out: Any) -> Any:
    if isinstance(out, BaseModel):
        return json.loads(out.model_dump_json())
    return out


def _strip_optional(ann: Any) -> Any:
    """Convert Optional[X] / X | None -> X. ADK auto-schema-gen emits type=NULL
    inside any_of for Optional, which Vertex AI rejects with BadRequest. Stripping
    keeps the param optional via signature default=None but drops null from schema."""
    origin = get_origin(ann)
    if origin in (Union, UnionType):
        non_none = [a for a in get_args(ann) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return ann


def _make_tool_fn(spec: ToolSpec, deps_ref: dict):
    """Build a callable for ADK FunctionTool that flattens input_model fields.

    deps_ref is a dict containing {'ctx': ToolContext, 'trace': list, 'calls': list}
    captured by closure so tools can write back to the per-turn collectors.
    """
    Model = spec.input_model
    fields = Model.model_fields

    async def tool_fn(**kwargs: Any) -> Any:
        try:
            inp = Model.model_validate(kwargs)
            if spec.is_async:
                out = await spec.callable(inp, deps_ref["ctx"])
            else:
                out = spec.callable(inp, deps_ref["ctx"])
            payload = _serialize(out)
            raised = None
        except Exception as e:
            payload = {"error": f"{type(e).__name__}: {e}"}
            raised = type(e).__name__
        deps_ref["calls"].append(ToolCallTrace(
            name=spec.name,
            args=kwargs,
            result_summary=json.dumps(payload, ensure_ascii=False, default=str)[:120],
            raised=raised,
        ))
        deps_ref["trace"].append(f"{spec.name}({json.dumps(kwargs, ensure_ascii=False)[:60]}) -> {str(payload)[:60]}")
        return payload

    params = []
    annotations: dict[str, Any] = {"return": Any}
    for fname, fld in fields.items():
        default = inspect.Parameter.empty if fld.is_required() else fld.default
        ann = _strip_optional(fld.annotation)
        params.append(inspect.Parameter(
            fname,
            inspect.Parameter.KEYWORD_ONLY,
            annotation=ann,
            default=default,
        ))
        annotations[fname] = ann
    tool_fn.__signature__ = inspect.Signature(params)
    tool_fn.__annotations__ = annotations
    tool_fn.__name__ = spec.name
    tool_fn.__doc__ = spec.description
    return tool_fn


def _build_instruction(state: ChatSessionState) -> str:
    parts = [SYSTEM_PROMPT]
    if state.history_summary:
        parts.append(f"\nconversation_summary: {state.history_summary}")
    if state.focused_episode_id and state.focused_is_fresh():
        parts.append(f"\nfocused_episode_id: {state.focused_episode_id} (pinned, may be stale for unrelated topics)")
    return "".join(parts)


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
class GoogleADKAdapter:
    name: str = "e_google_adk"
    # ADK session_service is created lazily per adapter instance
    _session_service: Any = None
    _runner_cache: dict[str, Any] = field(default_factory=dict)

    async def run_turn(
        self, question: str, session_id: str, ctx: ToolContext
    ) -> TurnResult:
        from google.adk.agents import LlmAgent
        from google.adk.tools import FunctionTool
        from google.adk.models.lite_llm import LiteLlm
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types as genai_types

        tracker = TurnTracker()
        deps_ref: dict[str, Any] = {"ctx": ctx, "trace": [], "calls": []}
        state = load_state(ctx.redis_client, session_id, ctx.show_id)

        # AI Hub creds
        async with ctx.db_factory() as db:
            step = await get_step_config(db, "summary")

        adk_tools = [FunctionTool(_make_tool_fn(t, deps_ref)) for t in TOOLS]
        agent = LlmAgent(
            name="bakeoff_e_agent",
            model=LiteLlm(model=f"openai/{MAIN_MODEL}", api_base=step.base_url, api_key=step.api_key),
            instruction=_build_instruction(state),
            tools=adk_tools,
        )
        if self._session_service is None:
            self._session_service = InMemorySessionService()
        runner = Runner(app_name=APP_NAME, agent=agent, session_service=self._session_service, auto_create_session=True)

        new_message = genai_types.Content(role="user", parts=[genai_types.Part(text=question)])

        final_answer = ""
        wall_t0 = time.perf_counter()
        total_input_tokens = 0
        total_output_tokens = 0
        try:
            async for event in runner.run_async(
                user_id="bakeoff_user",
                session_id=session_id,
                new_message=new_message,
            ):
                if event.usage_metadata is not None:
                    total_input_tokens += getattr(event.usage_metadata, "prompt_token_count", 0) or 0
                    total_output_tokens += getattr(event.usage_metadata, "candidates_token_count", 0) or 0
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        txt = getattr(part, "text", None)
                        if txt and event.author != "user":
                            final_answer = txt.strip()
        except Exception as e:
            deps_ref["trace"].append(f"AGENT ERROR: {type(e).__name__}: {e}")
            final_answer = f"(adk error: {type(e).__name__}: {e})"

        wall_ms = (time.perf_counter() - wall_t0) * 1000
        tracker.record(MAIN_MODEL, total_input_tokens, total_output_tokens, wall_ms)

        # L0 history compression (same out-of-band as A/B)
        compress_client = OpenAI(api_key=step.api_key, base_url=step.base_url)
        state.history_summary = _compress_history(
            compress_client, state.history_summary, question, final_answer, tracker
        )
        save_state(ctx.redis_client, state)

        return TurnResult(
            answer=final_answer,
            tool_calls=deps_ref["calls"],
            wall_latency_ms=tracker.wall_latency_ms(),
            cost_usd=tracker.total_cost_usd,
            input_tokens=tracker.total_input_tokens,
            output_tokens=tracker.total_output_tokens,
            trace_log="\n".join(deps_ref["trace"]),
        )

    async def reset_session(self, session_id: str) -> None:
        if self._session_service is None:
            return
        try:
            await self._session_service.delete_session(
                app_name=APP_NAME, user_id="bakeoff_user", session_id=session_id
            )
        except Exception:
            pass
