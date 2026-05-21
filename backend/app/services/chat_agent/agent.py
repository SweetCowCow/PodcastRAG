"""Chat agent loop (chat-agentic-tool-routing change).

`run_agent` drives the OpenAI-compatible tool-calling loop against the AI Hub
endpoint, using the `answer` AI step config. The loop iterates up to
`settings.agentic_chat_max_iterations` rounds, dispatching tool calls via
the tool registry in `tools.py` and accumulating a `ToolCallTrace` per
dispatch.

On max-iteration cap: returns the last LLM message content + `agent_truncated=True`.
On tool exception: caught inside `_dispatch_tool`, returned as error JSON — loop
never propagates tool failures as 5xx.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field

from openai import AsyncOpenAI, OpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.query import ToolCallTrace
from app.services.ai_step_resolver import AiStepNotConfiguredError, get_step_config
from app.services.chat_agent.memory import build_messages, update_history_summary
from app.services.chat_agent.state import ChatSessionState, ChatSessionStateStore
from app.services.chat_agent.tools import OPENAI_TOOLS_SPEC, ToolContext, _dispatch_tool

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class LLMCallTrace:
    """Per-round LLM API call telemetry collected by `run_agent`.

    `prompt_tokens` is the round-total prompt token count reported by the
    provider (includes all accumulated history + tool messages, not just the
    delta for this round). `completion_tokens` is delta-only as usual.
    """

    round_index: int
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    had_tool_calls: bool


@dataclass
class StageTimings:
    build_messages_ms: float = 0.0
    state_load_ms: float = 0.0
    state_save_ms: float = 0.0
    history_summary_ms: float = 0.0
    llm_loop_total_ms: float = 0.0


@dataclass
class ChatAgentResult:
    answer: str
    tool_calls: list[ToolCallTrace]
    agent_truncated: bool
    l1_state_after: ChatSessionState
    usage: TokenUsage = field(default_factory=TokenUsage)
    llm_calls: list[LLMCallTrace] = field(default_factory=list)
    stage_timings: StageTimings = field(default_factory=StageTimings)


async def run_agent(
    question: str,
    session_id: uuid.UUID,
    show_id: uuid.UUID,
    db: AsyncSession,
) -> ChatAgentResult:
    """Drive the OpenAI tool-calling loop for a single chat turn.

    Loads (or creates) the L1 session state, builds the context window,
    iterates the LLM up to `agentic_chat_max_iterations` rounds dispatching
    tools, and returns a `ChatAgentResult`. Never raises 5xx from tool failures.
    """
    answer_cfg = await get_step_config(db, "answer")
    client = AsyncOpenAI(
        base_url=answer_cfg.base_url,
        api_key=answer_cfg.api_key,
    )

    stage_timings = StageTimings()
    llm_calls: list[LLMCallTrace] = []

    state_store = ChatSessionStateStore()
    _t = time.perf_counter()
    state = state_store.load(session_id) or ChatSessionState(session_id=session_id)
    stage_timings.state_load_ms = (time.perf_counter() - _t) * 1000.0

    _t = time.perf_counter()
    messages = build_messages(state, [], question)
    stage_timings.build_messages_ms = (time.perf_counter() - _t) * 1000.0

    trace: list[ToolCallTrace] = []
    agent_truncated = False
    answer = ""
    usage = TokenUsage()
    ctx = ToolContext(db=db, show_id=show_id, state=state, state_store=state_store)

    loop_t0 = time.perf_counter()
    for round_index in range(settings.agentic_chat_max_iterations):
        _llm_t = time.perf_counter()
        response = await client.chat.completions.create(
            model=answer_cfg.model,
            messages=messages,
            tools=OPENAI_TOOLS_SPEC,
            tool_choice="auto",
        )
        llm_latency_ms = (time.perf_counter() - _llm_t) * 1000.0
        choice = response.choices[0]
        msg = choice.message

        if response.usage:
            usage.prompt_tokens += response.usage.prompt_tokens or 0
            usage.completion_tokens += response.usage.completion_tokens or 0

        llm_calls.append(
            LLMCallTrace(
                round_index=round_index,
                latency_ms=llm_latency_ms,
                prompt_tokens=(response.usage.prompt_tokens or 0) if response.usage else 0,
                completion_tokens=(response.usage.completion_tokens or 0) if response.usage else 0,
                finish_reason=choice.finish_reason or "",
                had_tool_calls=bool(msg.tool_calls),
            )
        )

        # Append assistant message to running context window.
        assistant_msg: dict = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if not msg.tool_calls:
            answer = msg.content or ""
            break

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            result_dict, raised, latency_ms = await _dispatch_tool(
                tool_name, tool_args, ctx
            )
            result_str = json.dumps(result_dict, ensure_ascii=False)

            trace.append(
                ToolCallTrace(
                    name=tool_name,
                    args=tool_args,
                    result_summary=result_str[:500],
                    raised=raised,
                    latency_ms=latency_ms,
                    # agent-trace-telemetry task 4.1: always store the full
                    # result_str here. API layer scrubs to None when the admin
                    # debug_trace gate is not active (task 4.2).
                    result_full=result_str,
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                }
            )
    else:
        # Reached max_iterations without a terminal answer message.
        agent_truncated = True
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "assistant":
                answer = m.get("content") or ""
                break
    stage_timings.llm_loop_total_ms = (time.perf_counter() - loop_t0) * 1000.0

    _t = time.perf_counter()
    await _try_update_summary(db, state, question, answer)
    stage_timings.history_summary_ms = (time.perf_counter() - _t) * 1000.0

    _t = time.perf_counter()
    try:
        state_store.save(state)
    except Exception:
        logger.exception("chat_agent: L1 state persist failed (non-fatal)")
    stage_timings.state_save_ms = (time.perf_counter() - _t) * 1000.0

    return ChatAgentResult(
        answer=answer,
        tool_calls=trace,
        agent_truncated=agent_truncated,
        l1_state_after=state,
        usage=usage,
        llm_calls=llm_calls,
        stage_timings=stage_timings,
    )


async def _try_update_summary(
    db: AsyncSession,
    state: ChatSessionState,
    question: str,
    answer: str,
) -> None:
    """Build a sync summarizer from the `summary` step config and call
    `update_history_summary`. Entirely fail-open."""
    try:
        summary_cfg = await get_step_config(db, "summary")
        sync_client = OpenAI(base_url=summary_cfg.base_url, api_key=summary_cfg.api_key)
        model = summary_cfg.model

        def _summarize(prompt: str) -> str:
            resp = sync_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )
            return resp.choices[0].message.content or ""

        await asyncio.to_thread(
            update_history_summary,
            state,
            {"user": question, "assistant": answer},
            summarizer=_summarize,
        )
    except AiStepNotConfiguredError:
        pass
    except Exception:
        logger.exception("chat_agent: history summary update failed (non-fatal)")
