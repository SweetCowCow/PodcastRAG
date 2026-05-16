"""LLM prompt templates for the RAG answer pipeline.

R2.1 (Decision 4): the answer model is told to enumerate sources `[1] [2] [3]…`
and to end every factual sentence with a bracketed reference token. Multi-source
synthesis uses `[N,M,...]` (no `[multi]` — see Open Question resolution in
the design). The response shape (`{"answer": ..., "used_chunk_ids": [...]}`)
is unchanged so the existing parser in `rag.answer_with_chunks` keeps working
without breakage.

R2.1-fix (2026-05-10): post-launch eval showed the original prompt over-refused
(Pattern A), polluted answers with `[N]` noise (Pattern B), doubled latency by
bloating system tokens (Pattern C), and forced a mechanical refusal string
that judges disliked (Pattern D). This module is the rewrite — see
`docs/case-studies/r21-prompt-regression-2026-05-10.md` for the diagnosis.

Bilingual refusal directive per spec scenario "Empty retrieval triggers
explicit refusal":
    zh → 找不到相關內容，請改用其他關鍵字
    en → No relevant content was found. Please try different keywords.
"""
from __future__ import annotations

from typing import Literal

Lang = Literal["zh", "en"]

# Refusal strings — kept for backward-compat. The R2.1-fix prompt no longer
# forces the LLM to emit this exact phrase; tests that assert on the substring
# still pass for callers that emit the literal, but the model is now free to
# phrase its refusal naturally.
REFUSAL_TEXT: dict[Lang, str] = {
    "zh": "找不到相關內容，請改用其他關鍵字",
    "en": "No relevant content was found. Please try different keywords.",
}


# R2.1-fix Fix 4: zh / en share one skeleton with surface-only swaps. The
# faithfulness rules (Fix 3) and refusal style (Fix 2) live in the surface
# strings — the structure stays identical so we don't double-maintain logic.

_SURFACE: dict[Lang, dict[str, str]] = {
    "zh": {
        "intro": "你是 podcast 問答助理。請優先依據下方 sources 回答；回覆語言與使用者問題語言一致。",
        "citation_header": "Citation 規範：",
        "citation_single": "- 每一句陳述事實的句子，句尾請加上對應 source 編號 token，例如 `[1]` 或 `[1,3]`。",
        "citation_range": "- 編號必須在 1..N 範圍內；不在範圍的編號後端會 strip 掉。",
        "faithfulness_header": "Faithfulness 規範：",
        "faithfulness_facts": "- 具體事實點（人名、數字、地點、時間、引述原話）必須來自 sources，不得杜撰。",
        "faithfulness_synth": "- 可以對 sources 做語意彙整、合理推論主旨，不必每個字都直接複製。",
        "faithfulness_partial": "- sources 只給片段資訊時，請把已知部分講清楚並說明哪部分尚無資料，不要整段拒答。",
        "refusal_header": "拒答規範：",
        "refusal": (
            "- 當 sources 完全無法支撐問題時，用自然中文回應，例如："
            "「目前的資料裡沒有提到 X，建議用其他關鍵字試試。」（請把 X 換成問題實際在問的主題詞）。"
        ),
        "format_header": "回應格式：",
        "format_body": (
            '必須是合法 JSON object：'
            '{"answer": "<你的回答（含 [N] / [N,M] token）>", '
            '"used_chunk_ids": ["ep:<episode_id>@<start_time>" 或 "desc:<episode_id>", ...]}'
        ),
        "format_note": "`used_chunk_ids` 只列出實際引用的 source 編號對應的 key。",
        "sources_header": "Sources:",
    },
    "en": {
        "intro": "You are a podcast Q&A assistant. Prefer answering from the sources below; reply in the user's question language.",
        "citation_header": "Citation rules:",
        "citation_single": "- End each factual sentence with the matching source token, e.g. `[1]` or `[1,3]`.",
        "citation_range": "- Numbers must be within 1..N; out-of-range tokens are stripped server-side.",
        "faithfulness_header": "Faithfulness rules:",
        "faithfulness_facts": "- Concrete facts (names, numbers, places, times, direct quotes) must come from sources — never invent them.",
        "faithfulness_synth": "- You may synthesise themes and infer main points across sources without quoting verbatim.",
        "faithfulness_partial": "- When sources only give partial info, state what is known and flag what is missing — do not refuse outright.",
        "refusal_header": "Refusal:",
        "refusal": (
            "- If no source can support the question, reply naturally, e.g. "
            "\"The provided material doesn't mention X — try a different keyword.\" "
            "(replace X with the actual topic the user asked about)."
        ),
        "format_header": "Response format:",
        "format_body": (
            'Must be a valid JSON object: '
            '{"answer": "<your answer with [N] / [N,M] tokens>", '
            '"used_chunk_ids": ["ep:<episode_id>@<start_time>" or "desc:<episode_id>", ...]}'
        ),
        "format_note": "`used_chunk_ids` lists only the source keys you actually cited.",
        "sources_header": "Sources:",
    },
}


def _format_chunks_block(chunks: list[tuple[str, str, str]]) -> str:
    """`chunks` is a list of (source_key, episode_title, text) triples.

    R2.1-fix Fix 4: only the body text is sent to the LLM (prefixed with
    `[N]`). The `source_key` and `episode_title` are kept in the function
    signature for caller compatibility but are NOT rendered into the prompt
    — they bloat token count and the LLM doesn't need them to cite. The
    backend still maps `used_chunk_ids` back to keys via the retrieval order.
    """
    parts: list[str] = []
    for idx, (_key, _title, body) in enumerate(chunks, start=1):
        parts.append(f"[{idx}]\n{body}")
    return "\n\n".join(parts)


def _render_template(lang: Lang, chunks_block: str) -> str:
    s = _SURFACE[lang]
    return (
        f"{s['intro']}\n\n"
        f"{s['citation_header']}\n"
        f"{s['citation_single']}\n"
        f"{s['citation_range']}\n\n"
        f"{s['faithfulness_header']}\n"
        f"{s['faithfulness_facts']}\n"
        f"{s['faithfulness_synth']}\n"
        f"{s['faithfulness_partial']}\n\n"
        f"{s['refusal_header']}\n"
        f"{s['refusal']}\n\n"
        f"{s['format_header']}\n"
        f"{s['format_body']}\n"
        f"{s['format_note']}\n\n"
        f"{s['sources_header']}\n"
        f"{chunks_block}\n"
    )


def render_answer_prompt(
    chunks: list[tuple[str, str, str]],
    lang: Lang = "zh",
    enumeration_block: str | None = None,
) -> str:
    """Render the answer system prompt with `[1] [2] [3]…` numbered sources.

    `chunks` is the list of source rows (key, title, text) in retrieval order.
    Numbering is 1-based. An empty `chunks` list is allowed — the prompt then
    instructs the model to answer with a natural-language refusal.

    `enumeration_block` (r3-3-chat-enum-grounding) is an optional pre-rendered
    block listing the cross-episode enumeration results. When non-None it is
    prepended BEFORE the source chunks so the answer model grounds its prose
    count on the enumeration list instead of inferring "N episodes" from the
    top-K chunk subset it happened to retrieve. See
    `app.services.episode_finders` for the producer and
    `format_enumeration_block` in `app.services.rag` for the renderer.
    """
    block = _format_chunks_block(chunks)
    rendered = _render_template(lang, block)
    if enumeration_block:
        rendered = enumeration_block.rstrip() + "\n\n" + rendered
    return rendered
