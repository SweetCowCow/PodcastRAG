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
import re
import time
import uuid
from dataclasses import dataclass, field

import openai
from openai import AsyncOpenAI, OpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.query import ToolCallTrace
from app.services.ai_step_resolver import AiStepNotConfiguredError, get_step_config
from app.services.chat_agent.memory import build_messages, update_history_summary
from app.services.chat_agent.state import ChatSessionState, ChatSessionStateStore
from app.services.chat_agent.tools import OPENAI_TOOLS_SPEC, ToolContext, _dispatch_tool

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Token-budget + truncate helpers (agent-token-budget-and-tool-truncate)
# ──────────────────────────────────────────────────────────────────────


def _truncate_for_llm(s: str, cap: int) -> str:
    """Cap a tool-result string for the LLM-facing message body.

    Returns `s` unchanged when within cap. Otherwise returns the first
    `cap` chars plus a literal suffix `... (truncated, <N> chars omitted)`
    so the LLM can see the truncation happened (and is expected to wrap
    up rather than ask for more).
    """
    if cap <= 0 or len(s) <= cap:
        return s
    omitted = len(s) - cap
    return f"{s[:cap]}... (truncated, {omitted} chars omitted)"


def _estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate total tokens in the running messages list.

    Uses `tiktoken` gpt-4o encoder when available; falls back to a coarse
    `len(text) / 4` heuristic (LLM-tokens-per-char approximation) when the
    encoder is unavailable or fails to load. This is conservative enough
    to drive the budget guard — over-estimating by ~10% just makes the
    guard trip slightly earlier.
    """
    try:
        import tiktoken  # type: ignore

        try:
            enc = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        total = 0
        for m in messages:
            total += len(enc.encode(json.dumps(m, ensure_ascii=False)))
        return total
    except Exception:
        return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) // 4


def _apply_budget_guard(
    messages: list[dict], budget: int
) -> tuple[bool, int]:
    """Trim oldest tool messages until estimated tokens fit within `budget`.

    Preserves the leading system message(s) and the most recent user / assistant
    pair. Returns `(fits, popped_count)`:
        - `fits=True` if the trimmed list is at or under budget
        - `fits=False` if we ran out of removable tool messages and still
          exceed budget (caller SHALL finalise the loop)
    """
    popped = 0
    while _estimate_messages_tokens(messages) > budget:
        # Find oldest tool-role message NOT in the most-recent pair.
        # Preserve any leading role="system" + the final user + final assistant.
        tool_idx = None
        for i, m in enumerate(messages):
            if m.get("role") == "tool":
                # Guard: don't pop a tool message from the very last round
                # (i.e. one that immediately precedes the final assistant);
                # otherwise the LLM sees a tool_call without its tool reply.
                # Simple heuristic: never pop the last 2 tool messages.
                if i < len(messages) - 2:
                    tool_idx = i
                    break
        if tool_idx is None:
            return False, popped
        messages.pop(tool_idx)
        popped += 1
    return True, popped


def _classify_llm_exception(exc: BaseException) -> str | None:
    """Return envelope `kind` for known LLM-side failures, else None.

    `context_exceeded` is the only kind we handle here (gpt-4o 128K cap via
    AI Hub surfaces as `openai.BadRequestError` with body mentioning
    `ContextWindowExceededError`). Other 4xx / 5xx are re-raised so the
    endpoint-level handler in `query.py` can route them.
    """
    if not isinstance(exc, openai.BadRequestError):
        return None
    text_blob = ""
    try:
        body = getattr(exc, "body", None) or {}
        if isinstance(body, dict):
            text_blob = json.dumps(body, ensure_ascii=False)
        else:
            text_blob = str(body)
    except Exception:
        text_blob = ""
    text_blob = text_blob + " " + str(exc)
    if "ContextWindowExceededError" in text_blob or "context_length" in text_blob:
        return "context_exceeded"
    return None


_CONTEXT_EXCEEDED_USER_HINT = (
    "這題涉及的內容太多，我只能列出部分結果；試試把問題拆小，"
    "譬如指定單一集數或縮小範圍。"
)


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
class EnumerationStateSnapshotInternal:
    """state.last_enumeration_episodes captured at build_messages time
    for the current turn. Plain dataclass to keep agent.py free of
    schemas; query.py converts to the response model."""

    last_enumeration_episodes: list[str] = field(default_factory=list)
    last_enumeration_at: str | None = None
    user_question: str = ""


@dataclass
class ChatAgentResult:
    answer: str
    tool_calls: list[ToolCallTrace]
    agent_truncated: bool
    l1_state_after: ChatSessionState
    usage: TokenUsage = field(default_factory=TokenUsage)
    llm_calls: list[LLMCallTrace] = field(default_factory=list)
    stage_timings: StageTimings = field(default_factory=StageTimings)
    unverified_count: int = 0
    enumeration_snapshot: EnumerationStateSnapshotInternal | None = None


# Post-generation citation scan (agentic-severe-residual-fix-2026-05).
# Matches:
#   - EP\d+ tokens (case-insensitive)
#   - quoted strings of ≥4 chars inside 「…」 (CJK) or "…" (ASCII)
_EP_TOKEN_RE = re.compile(r"EP\d+", re.IGNORECASE)
_QUOTE_RE = re.compile(r"「([^」]{4,})」|\"([^\"]{4,})\"")
_UNVERIFIED_SUFFIX = "[未驗證]"


def _annotate_unverified_tokens(
    answer: str, tool_calls: list[ToolCallTrace]
) -> tuple[str, int]:
    """Append `[未驗證]` after every EP-token and quoted string in `answer`
    that does NOT appear as a substring in the concatenation of all
    `tool_calls[].result_full` strings.

    Tokens already followed by `[未驗證]` (e.g. from a prior annotation)
    are not re-annotated. Returns the annotated answer + the count of
    annotations applied.
    """
    if not answer:
        return answer, 0
    reference_blob = "\n".join(
        (tc.result_full or "") for tc in tool_calls if getattr(tc, "result_full", None)
    )
    if not reference_blob:
        # No tool results to verify against — leave the answer untouched.
        # The agent's grounded-refusal rules should already cover this path.
        return answer, 0

    count = 0

    def _annotate_ep(m: re.Match) -> str:
        nonlocal count
        token = m.group(0)
        end = m.end()
        # Don't double-annotate.
        if answer.startswith(_UNVERIFIED_SUFFIX, end):
            return token
        if token in reference_blob:
            return token
        count += 1
        return token + _UNVERIFIED_SUFFIX

    annotated = _EP_TOKEN_RE.sub(_annotate_ep, answer)

    def _annotate_quote(m: re.Match) -> str:
        nonlocal count
        full = m.group(0)
        inner = m.group(1) or m.group(2) or ""
        end = m.end()
        if annotated.startswith(_UNVERIFIED_SUFFIX, end):
            return full
        if inner in reference_blob:
            return full
        count += 1
        return full + _UNVERIFIED_SUFFIX

    annotated = _QUOTE_RE.sub(_annotate_quote, annotated)
    return annotated, count


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
    enumeration_snapshot = EnumerationStateSnapshotInternal(
        last_enumeration_episodes=[str(e) for e in state.last_enumeration_episodes],
        last_enumeration_at=(
            state.last_enumeration_at.isoformat() if state.last_enumeration_at else None
        ),
        user_question=question,
    )
    messages = build_messages(state, [], question)
    stage_timings.build_messages_ms = (time.perf_counter() - _t) * 1000.0

    trace: list[ToolCallTrace] = []
    agent_truncated = False
    answer = ""
    usage = TokenUsage()
    ctx = ToolContext(db=db, show_id=show_id, state=state, state_store=state_store)

    loop_t0 = time.perf_counter()
    for round_index in range(settings.agentic_chat_max_iterations):
        # Per-round token-budget guard. Trim oldest tool messages until
        # estimated tokens fit; if we cannot fit, finalise this round.
        _fits, _popped = _apply_budget_guard(
            messages, settings.agentic_chat_messages_max_tokens
        )
        if _popped:
            logger.warning(
                "agent budget guard: popped %d oldest tool message(s) at round %d",
                _popped,
                round_index,
            )
        if not _fits:
            logger.warning(
                "agent budget guard: cannot fit budget at round %d, finalising", round_index
            )
            messages.append({
                "role": "system",
                "content": "Context truncated by budget guard. Wrap up with the information you already have.",
            })
            agent_truncated = True
            # Use the most recent assistant content (if any) as the answer.
            for m in reversed(messages):
                if m.get("role") == "assistant" and m.get("content"):
                    answer = m["content"]
                    break
            break

        _llm_t = time.perf_counter()
        try:
            response = await client.chat.completions.create(
                model=answer_cfg.model,
                messages=messages,
                tools=OPENAI_TOOLS_SPEC,
                tool_choice="auto",
            )
        except openai.BadRequestError as exc:
            kind = _classify_llm_exception(exc)
            if kind != "context_exceeded":
                raise  # other 4xx routes through endpoint handler
            llm_latency_ms = (time.perf_counter() - _llm_t) * 1000.0
            logger.warning(
                "agent LLM context_exceeded at round %d: %s",
                round_index,
                type(exc).__name__,
            )
            llm_calls.append(
                LLMCallTrace(
                    round_index=round_index,
                    latency_ms=llm_latency_ms,
                    prompt_tokens=0,
                    completion_tokens=0,
                    finish_reason="context_exceeded",
                    had_tool_calls=False,
                )
            )
            answer = _CONTEXT_EXCEEDED_USER_HINT
            agent_truncated = True
            break
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
            # LLM-facing body is capped; result_full keeps the original
            # for admin debug_trace (no observability degradation).
            truncated_str = _truncate_for_llm(
                result_str, settings.agentic_tool_result_max_chars
            )

            trace.append(
                ToolCallTrace(
                    name=tool_name,
                    args=tool_args,
                    result_summary=truncated_str[:500],
                    raised=raised,
                    latency_ms=latency_ms,
                    # agent-trace-telemetry task 4.1: always store the full
                    # (untruncated) result_str here. API layer scrubs to None
                    # when the admin debug_trace gate is not active.
                    result_full=result_str,
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": truncated_str,
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

    answer, unverified_count = _annotate_unverified_tokens(answer, trace)

    return ChatAgentResult(
        answer=answer,
        tool_calls=trace,
        agent_truncated=agent_truncated,
        l1_state_after=state,
        usage=usage,
        llm_calls=llm_calls,
        stage_timings=stage_timings,
        unverified_count=unverified_count,
        enumeration_snapshot=enumeration_snapshot,
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
