"""RAG answer generation.

LLM-facing layer: question rewriting, the enumeration grounding block, answer
generation with JSON parsing + salvage, and citation stripping. Wraps the
OpenAI client with api_health tracking via ``_chat_with_tracker``.
"""
from __future__ import annotations

import json as _stdlib_json
import re
import time

from openai import OpenAI

from app.services import api_health
from app.services.llm_prompts import Lang, render_answer_prompt
from app.services.rag_config import HISTORY_WINDOW
from app.services.rag_types import ChunkHit

__all__ = [
    "REWRITE_SYSTEM_PROMPT",
    "ENUMERATION_BLOCK_MAX_LIST_ROWS",
    "rewrite_question",
    "format_enumeration_block",
    "answer_with_chunks",
    "strip_citations",
    "_chat_with_tracker",
    "_hit_key",
    "_extract_answer_from_malformed_json",
    "_unwrap_self_referential_json",
]


REWRITE_SYSTEM_PROMPT = (
    "You rewrite a follow-up question into a standalone question, preserving the "
    "original intent and language. Use conversation history only to resolve "
    "pronouns and implicit references. Output ONLY the rewritten question, no "
    "preamble."
)

# R2.1 Decision 4: the answer prompt now lives in `app.services.llm_prompts`
# and enumerates sources as `[1] [2] [3]…`. The legacy single-template constant
# is removed; callers should use `render_answer_prompt(chunks, lang)`.


def _chat_with_tracker(client: OpenAI, **kwargs):
    start_ns = time.monotonic_ns()
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:
        duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        http_status = getattr(exc, "status_code", None)
        api_health.record(
            "openai_chat",
            ok=False,
            duration_ms=duration_ms,
            error_category=api_health.classify_error(exc, http_status),
            http_status=http_status,
        )
        raise
    duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000
    api_health.record(
        "openai_chat", ok=True, duration_ms=duration_ms, http_status=200
    )
    return resp


def rewrite_question(
    client: OpenAI,
    model: str,
    messages: list[dict],
    question: str,
) -> str:
    history = messages[-HISTORY_WINDOW:]
    chat_messages = [{"role": "system", "content": REWRITE_SYSTEM_PROMPT}]
    chat_messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    chat_messages.append({"role": "user", "content": question})

    resp = _chat_with_tracker(client, model=model, messages=chat_messages)
    return (resp.choices[0].message.content or "").strip() or question


# r3-3-chat-enum-grounding: cap on how many episodes get listed inside the
# answer prompt's grounding block. Beyond this we truncate (the response
# body still carries the full list — the cap protects prompt token budget).
# 30 × ~60 token ≈ 1800 token, comfortable under gpt-4o-mini's 128k window
# while leaving headroom for the chunk citations block + few-shot history.
ENUMERATION_BLOCK_MAX_LIST_ROWS = 30


def format_enumeration_block(
    *,
    episodes: list,
    total: int,
    fallback_marker: str,
    entities,
) -> str:
    """Render the grounding block that prepends the answer prompt.

    Inputs come from `_compute_enumeration_episodes` in `app/api/query.py`:
    - `episodes` is `list[EpisodeRef]` (possibly empty when the filter
      matched zero rows); ordered by `published_at DESC NULLS LAST`.
    - `total` mirrors `len(episodes)` today (no backend cap) — kept as
      its own arg so a future paginated backend can pass the real total.
    - `fallback_marker` is `"none"` for direct matches, `"guest_only"`
      when guest+topic AND was empty and we fell back to guests-only.
    - `entities` is the `QueryEntities` instance — used to surface the
      guest name in the `guest_only` fallback header so the LLM has the
      exact noun to echo back.

    Returns a multi-line string. The 0-episode case still produces a
    block — the answer model needs to see "no match found" rather than
    silently get no enumeration context.
    """
    if not episodes:
        return "## 沒有找到相符的集數\n（系統依條件搜尋後沒有符合的集數，請在回答中明確說明沒有找到）"

    listed = episodes[:ENUMERATION_BLOCK_MAX_LIST_ROWS]
    truncated = total > ENUMERATION_BLOCK_MAX_LIST_ROWS

    # Header decides between three shapes:
    # - guest_only fallback: warn that no episode satisfied both filters
    # - truncated (>30 rows): show "of N, listing newest 30"
    # - normal: show "(共 N 集)"
    if fallback_marker == "guest_only":
        guest_name = ", ".join(entities.guests) if getattr(entities, "guests", None) else ""
        if guest_name:
            header = f"## ⚠ 沒有完全相符的集數，以下是「{guest_name}」全部上過的集數（共 {total} 集）"
        else:
            header = f"## ⚠ 沒有完全相符的集數，以下列出可用的集數（共 {total} 集）"
    elif truncated:
        header = f"## 相關集數清單（共 {total} 集，以下列出最新 {ENUMERATION_BLOCK_MAX_LIST_ROWS} 集）"
    else:
        header = f"## 相關集數清單（共 {total} 集）"

    lines = [header, "這個問題的搜尋結果鎖定以下集數，作為你回答的依據："]
    for idx, ep in enumerate(listed, start=1):
        date_str = ep.published_at.strftime("%Y-%m-%d") if ep.published_at else "未知日期"
        guests_part = ""
        if ep.guests:
            guests_part = f", ft. {', '.join(ep.guests)}"
        lines.append(f"{idx}. {ep.title} ({date_str}{guests_part})")
    return "\n".join(lines)


def _hit_key(hit: ChunkHit) -> str:
    if hit.source == "description":
        return f"desc:{hit.episode_id}"
    return f"ep:{hit.episode_id}@{hit.start_time:.2f}"


# R2.1-fix Fix 1: strip every `[N]` / `[N,M,...]` bracket ref token from an
# answer string. Used by eval / judge consumers that should not see the inline
# citation noise (the frontend renders the raw answer where `[N]` is meaningful;
# `citation_parser.parse` already strips invalid tokens for the API path).
_CITATION_TOKEN_RE = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")

# Fallback extractor for the answer_with_chunks JSON parse failure path:
# the LLM occasionally returns malformed JSON (e.g. `"used_chunk_ids": }`
# from an over-aggressive truncation). The `try/except` below used to return
# the raw string verbatim, which leaked the JSON wrapping (`{"answer": "...",
# "used_chunk_ids":`) into the chat bubble shown to the user. This regex
# pulls the `answer` string field out even when surrounding JSON is invalid,
# so the user-visible text stays clean. DOTALL so `\n` inside the answer
# survives; non-greedy with negative-lookbehind handling for escaped quotes.
_ANSWER_FIELD_RE = re.compile(
    r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL
)


def _extract_answer_from_malformed_json(raw: str) -> str | None:
    """Try to pull just the `"answer": "..."` value out of a malformed JSON
    string. Returns None if no answer field is found. Unescapes JSON-style
    `\\n` / `\\"` so the user sees real newlines / quotes."""
    m = _ANSWER_FIELD_RE.search(raw)
    if not m:
        return None
    try:
        return _stdlib_json.loads('"' + m.group(1) + '"')
    except ValueError:
        # Last-ditch manual unescape — covers the common cases.
        s = m.group(1)
        return s.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def _unwrap_self_referential_json(answer: str) -> str:
    """Unwrap a self-referential JSON answer string.

    The LLM occasionally returns the entire chat-completion payload as a
    JSON string assigned to the `answer` field, i.e. the outer JSON parses
    cleanly but `answer` is itself `'{"answer":"<real answer>"}'`. When this
    happens the judge sees the JSON wrapper instead of the prose and scores
    the item incorrectly (R2.1 RCA found this on `thisno-core-com-004`).

    Strategy: if `answer` looks like a JSON object (starts with `{`) and
    parses to a dict containing a string `"answer"` key, return that inner
    value. Otherwise return the original string untouched.
    """
    if not isinstance(answer, str):
        return answer
    s = answer.strip()
    if not s.startswith("{"):
        return answer
    try:
        parsed = _stdlib_json.loads(s)
    except ValueError:
        return answer
    if isinstance(parsed, dict):
        inner = parsed.get("answer")
        if isinstance(inner, str):
            return inner
    return answer


def strip_citations(text: str) -> str:
    """Remove every `[N]` / `[N,M,...]` bracket token (incl. preceding spaces).

    Returns an empty string for falsy input. Idempotent: running twice on a
    cleaned string returns the same string.
    """
    if not text:
        return ""
    return _CITATION_TOKEN_RE.sub("", text).strip()


def answer_with_chunks(
    client: OpenAI,
    model: str,
    messages: list[dict],
    question: str,
    chunks: list[ChunkHit],
    lang: Lang = "zh",
    enumeration_block: str | None = None,
) -> tuple[str, str, list[str]]:
    """Send the answer prompt to the LLM and parse the JSON reply.

    Returns `(answer_raw, answer_clean, used_ids)`:
    - `answer_raw` retains the LLM's `[N]` / `[N,M,...]` inline citation tokens
      so the frontend / `citation_parser.parse` can render source cards.
    - `answer_clean` has every `[N]` token stripped via `strip_citations`,
      suitable for sending to LLM judges or eval consumers that mistake the
      brackets for noise.

    `lang` controls which bilingual prompt + refusal directive is used
    (Decision 4 + spec scenarios "Empty retrieval triggers explicit refusal").

    `enumeration_block` (r3-3-chat-enum-grounding) is an optional pre-rendered
    system-prompt block listing the cross-episode enumeration matches. When
    supplied it is prepended BEFORE the chunk sources so the LLM grounds its
    prose count on the enumeration list rather than the top-K chunk subset.
    """
    import json as _json

    history = messages[-HISTORY_WINDOW:]
    rendered_chunks = [
        (_hit_key(c), c.episode_title, c.text) for c in chunks
    ]
    system_prompt = render_answer_prompt(
        rendered_chunks, lang=lang, enumeration_block=enumeration_block
    )

    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.extend({"role": m["role"], "content": m["content"]} for m in history)
    chat_messages.append({"role": "user", "content": question})

    resp = _chat_with_tracker(
        client,
        model=model,
        messages=chat_messages,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()

    try:
        parsed = _json.loads(raw)
        answer = parsed["answer"]
        # Guard against LLM occasionally double-wrapping the answer as a
        # JSON string (fix-eval-dataset-com-004-json-leak).
        answer = _unwrap_self_referential_json(answer)
        used_ids = [str(k) for k in parsed.get("used_chunk_ids", [])]
        return answer, strip_citations(answer), used_ids
    except (ValueError, KeyError):
        # JSON parse failed (often `"used_chunk_ids": }` malformed by LLM).
        # Salvage the `answer` field via regex so the chat bubble shows clean
        # prose instead of the JSON wrapping. used_chunk_ids stays empty so
        # all retrieved chunks fall through as citations.
        salvaged = _extract_answer_from_malformed_json(raw)
        if salvaged is not None:
            salvaged = _unwrap_self_referential_json(salvaged)
            return salvaged, strip_citations(salvaged), []
        return raw, strip_citations(raw), []
