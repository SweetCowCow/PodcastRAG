"""Message / history orchestration for the chat agent
（chat-agentic-tool-routing change）。

- `build_messages` 組 OpenAI chat-completions 用的 message list：SYSTEM
  prompt + history_summary（如有）+ L1 anchor 注入 + 最近 K=3 turn 完整
  message（保留 tool call round-trip）+ 當前 question。
- `update_history_summary` 用 `summary` AI step 增量壓縮對話到 ≤ 300 字，
  fail-open：任何 exception 都 log + 保留舊 summary，不擋主回答。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.services.chat_agent.prompts import SYSTEM_PROMPT
from app.services.chat_agent.state import ChatSessionState

logger = logging.getLogger(__name__)


_ORDINAL_INSTRUCTION = (
    "【序數參照規則 — 重要】使用者若說「第 N 集」「第三集」「第二個」「最後一集」等序數詞，"
    "**必須**用 `get_episode_summary` 直接查 `last_enumeration_episodes[N-1]` 的 ep_id，"
    "**禁止呼叫 `find_episode_by_ref`**（那是用來解 EP 編號 / 主題名 / 相對位置，不是序數）。"
    "若 N 超出 last_enumeration 長度，請使用者澄清而非翻譯成 EP<N>。"
)


def _build_system_message(state: ChatSessionState) -> str:
    parts: list[str] = [SYSTEM_PROMPT]
    if state.focused_episode_id is not None:
        parts.append(f"\n\nFocused episode: {state.focused_episode_id}")
    if state.last_enumeration_episodes:
        ep_list = ", ".join(str(e) for e in state.last_enumeration_episodes)
        parts.append(f"\n\nLast enumeration: [{ep_list}]\n{_ORDINAL_INSTRUCTION}")
    return "".join(parts)


def _keep_last_k_turns(history: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Return the tail of `history` covering the last `k` user turns. A turn
    spans one user message plus every assistant / tool message that follows
    it (i.e. tool-call round-trips are kept whole)."""

    if k <= 0 or not history:
        return []
    user_indices = [i for i, m in enumerate(history) if m.get("role") == "user"]
    if not user_indices:
        return list(history)
    if len(user_indices) <= k:
        return list(history)
    cut = user_indices[-k]
    return list(history[cut:])


def build_messages(
    state: ChatSessionState,
    history: list[dict[str, Any]],
    question: str,
) -> list[dict[str, Any]]:
    """Compose the message list passed to the OpenAI-compatible chat
    completion endpoint.

    Layout (top → bottom):
      1. SYSTEM message: SYSTEM_PROMPT + L1 anchors (focused / last_enumeration).
      2. SYSTEM message: prior `history_summary` (only when non-empty).
      3. Last K=3 turns from `history`, tool round-trips preserved.
      4. Current user `question`.
    """

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _build_system_message(state)}
    ]
    if state.history_summary:
        messages.append(
            {
                "role": "system",
                "content": f"先前對話摘要：{state.history_summary}",
            }
        )

    messages.extend(_keep_last_k_turns(history, settings.agentic_chat_l0_k_turns))
    messages.append({"role": "user", "content": question})
    return messages


def update_history_summary(
    state: ChatSessionState,
    last_turn: dict[str, str],
    *,
    summarizer,
) -> None:
    """Incrementally compress the rolling conversation summary using the
    `summary` AI step (gemini-2.5-flash-lite by default).

    `last_turn` SHOULD contain `{"user": ..., "assistant": ...}` strings.
    Mutates `state.history_summary` in place, capped to ≤ 300 chars.

    Fail-open: any exception is logged and `state.history_summary` is
    retained as-is. The caller MUST be able to continue serving the user
    even if summarisation fails.

    `summarizer` is a callable `(prompt: str) -> str`. The agent loop
    (`run_agent`) constructs the production summarizer from the
    `summary` AI step (gemini-2.5-flash-lite); tests pass mocks. Kept as
    a required injection seam so this module stays db-free and
    test-friendly.
    """

    try:
        prompt = _build_summary_prompt(state.history_summary, last_turn)
        new_summary = summarizer(prompt) or ""
        new_summary = new_summary.strip()[:300]
        state.history_summary = new_summary
    except Exception:
        logger.exception(
            "chat_agent.update_history_summary failed; retaining previous summary"
        )


def _build_summary_prompt(prior: str, last_turn: dict[str, str]) -> str:
    user = last_turn.get("user", "")
    assistant = last_turn.get("assistant", "")
    return (
        "請把以下對話增量壓縮成 ≤ 300 字的繁體中文摘要，保留事實型 anchor"
        "（集數編號、來賓、主題、使用者意圖），刪除寒暄與重複。"
        f"\n\n[先前摘要]\n{prior or '（無）'}"
        f"\n\n[最新一輪]\nUSER: {user}\nASSISTANT: {assistant}"
        "\n\n請直接輸出新摘要，不要前後加註解。"
    )
