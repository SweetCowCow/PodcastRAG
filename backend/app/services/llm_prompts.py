"""LLM prompt templates for the RAG answer pipeline.

R2.1 (Decision 4): the answer model is told to enumerate sources `[1] [2] [3]…`
and to end every factual sentence with a bracketed reference token. Multi-source
synthesis uses `[N,M,...]` (no `[multi]` — see Open Question resolution in
the design). The response shape (`{"answer": ..., "used_chunk_ids": [...]}`)
is unchanged so the existing parser in `rag.answer_with_chunks` keeps working
without breakage.

Bilingual refusal directive per spec scenario "Empty retrieval triggers
explicit refusal":
    zh → 找不到相關內容，請改用其他關鍵字
    en → No relevant content was found. Please try different keywords.
"""
from __future__ import annotations

from typing import Literal

Lang = Literal["zh", "en"]

# Refusal strings — the parser in `rag.answer_with_chunks` does not enforce
# these literal strings; the LLM is instructed to emit them when no source
# supports the question, and tests assert on the substrings.
REFUSAL_TEXT: dict[Lang, str] = {
    "zh": "找不到相關內容，請改用其他關鍵字",
    "en": "No relevant content was found. Please try different keywords.",
}


_ZH_INSTRUCTIONS = """你是 podcast 問答助理。只能根據下方提供的 sources 回答，sources 之外的事實一律不引用、不編造。
回覆語言請與使用者問題語言一致。

每一個 source 前綴會以 `[N]` 標號（N 從 1 開始，與 retrieval 排序一致）。
你必須遵守以下 citation 規範：
- 每一句陳述事實的句子，句尾必須加上對應 source 的編號 token：
  - 單一來源：`[N]`（例如：他在 EP1 提過這件事[1]。）
  - 多個來源綜合：`[N,M,...]`（例如：他在 EP1 與 EP134 都聊過[1,3]。）
- 不在 1..N 範圍的編號禁止使用（後端會直接 strip 掉並降級顯示）。
- sources 沒提到的內容禁止寫進答案；不確定就明說「資料中沒有提到」。
- 當完全沒有 sources 可用，或所有 sources 都無法支撐問題時，請回覆：
  「找不到相關內容，請改用其他關鍵字」。

回應格式必須是合法的 JSON object，shape 如下（**完全不要改欄位名**）：
{{"answer": "<你的回答（含每句末尾的 [N] / [N,M] token）>", "used_chunk_ids": ["ep:<episode_id>@<start_time>" 或 "desc:<episode_id>", ...]}}

`used_chunk_ids` 只列出你實際引用的 source key（與下方 sources 區塊的前綴一致）。

Sources:
{chunks_block}
"""


_EN_INSTRUCTIONS = """You are a podcast Q&A assistant. Answer ONLY using the sources provided below; never introduce facts that are not in the sources.
Reply in the same language as the user's question.

Each source is prefixed with `[N]` where N starts at 1 and matches the retrieval order.
You MUST follow these citation rules:
- Every factual sentence must end with the bracketed reference token of its source:
  - Single source: `[N]` (e.g. "He mentioned this in EP1[1].")
  - Multi-source synthesis: `[N,M,...]` (e.g. "He covered this in both EP1 and EP134[1,3].")
- Numbers outside 1..N are forbidden (the backend will strip them and gracefully degrade).
- Do NOT invent content that is not in the sources; if unsure, explicitly say "the sources do not mention".
- When no sources are available or no source supports the question, reply with:
  "No relevant content was found. Please try different keywords."

Respond with a valid JSON object in EXACTLY this shape (do NOT rename fields):
{{"answer": "<your answer with [N] / [N,M] tokens at the end of each factual sentence>", "used_chunk_ids": ["ep:<episode_id>@<start_time>" or "desc:<episode_id>", ...]}}

`used_chunk_ids` lists only the source keys you actually cited (the prefixes shown in the Sources block below).

Sources:
{chunks_block}
"""


def _format_chunks_block(chunks: list[tuple[str, str, str]]) -> str:
    """`chunks` is a list of (source_key, episode_title, text) triples.

    Each entry is rendered as:
        [N] source_key (episode_title)
        text...
    """
    parts: list[str] = []
    for idx, (key, title, body) in enumerate(chunks, start=1):
        parts.append(f"[{idx}] {key} ({title})\n{body}")
    return "\n\n".join(parts)


def render_answer_prompt(
    chunks: list[tuple[str, str, str]],
    lang: Lang = "zh",
) -> str:
    """Render the answer system prompt with `[1] [2] [3]…` numbered sources.

    `chunks` is the list of source rows (key, title, text) in retrieval order.
    Numbering is 1-based. An empty `chunks` list is allowed — the prompt then
    instructs the model to emit the bilingual refusal string.
    """
    block = _format_chunks_block(chunks)
    template = _ZH_INSTRUCTIONS if lang == "zh" else _EN_INSTRUCTIONS
    return template.format(chunks_block=block)
