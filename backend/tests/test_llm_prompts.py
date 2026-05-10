"""R2.1-fix: prompt directive + snapshot tests for the rewritten answer prompt.

The snapshot is the rendered prompt for a fixed three-source fixture in both
`zh` and `en`. If a prompt change is intentional, regenerate the expected
blocks below by running:

    python -m pytest backend/tests/test_llm_prompts.py -k snapshot -s

…and pasting the new output. Treat any unintended diff as a regression.

Background: R2.1 launched a heavyweight prompt that triggered Faithfulness
regression (case study: docs/case-studies/r21-prompt-regression-2026-05-10.md).
R2.1-fix shrinks the prompt, softens refusal phrasing, and stops sending
`source_key` / `episode_title` into the chunks block.
"""
from __future__ import annotations

from app.services.llm_prompts import render_answer_prompt


_FIXTURE_CHUNKS = [
    ("ep:e1@10.00", "EP1", "迪拉胖第一次來上節目時聊到童年。"),
    ("ep:e2@22.50", "EP2", "他在 EP2 又補充了相關背景。"),
    ("desc:e3", "EP3", "本集介紹了三首歌單。"),
]


def test_zh_prompt_contains_required_directives():
    out = render_answer_prompt(_FIXTURE_CHUNKS, lang="zh")
    # R2.1-fix Fix 4: chunks_block now `[N]\n{body}` only — no source_key / title.
    assert "[1]\n迪拉胖第一次來上節目時聊到童年。" in out
    assert "[2]\n他在 EP2 又補充了相關背景。" in out
    assert "[3]\n本集介紹了三首歌單。" in out
    # Source key and episode title MUST NOT be sent (Fix 4 token diet).
    assert "ep:e1@10.00" not in out
    assert "(EP1)" not in out
    # Citation contract still documented (Decision 4 — frontend depends on it).
    assert "[1]" in out and "[1,3]" in out
    # JSON shape unchanged so the existing parser keeps working.
    assert '"answer"' in out
    assert '"used_chunk_ids"' in out
    # R2.1-fix Fix 2: refusal is naturally phrased — no mechanical literal.
    assert "找不到相關內容，請改用其他關鍵字" not in out
    assert "X 換成" in out  # the "replace X with topic" instruction
    # R2.1-fix Fix 3: faithfulness is multi-tier, not a single "禁止編造" line.
    assert "杜撰" in out
    assert "語意彙整" in out
    assert "片段資訊" in out


def test_en_prompt_contains_required_directives():
    out = render_answer_prompt(_FIXTURE_CHUNKS, lang="en")
    assert "[1]\n迪拉胖第一次來上節目時聊到童年。" in out
    assert "[2]\n他在 EP2 又補充了相關背景。" in out
    assert "[3]\n本集介紹了三首歌單。" in out
    assert "ep:e1@10.00" not in out
    assert "(EP1)" not in out
    assert "[1]" in out and "[1,3]" in out
    assert '"answer"' in out
    assert '"used_chunk_ids"' in out
    # Naturally phrased refusal, not the mechanical fallback string.
    assert "No relevant content was found. Please try different keywords." not in out
    assert "replace X" in out
    # Multi-tier faithfulness clauses present.
    assert "never invent" in out
    assert "synthesise" in out
    assert "partial info" in out


def test_empty_chunks_still_renders_with_refusal_directive():
    """When retrieval returned zero chunks the prompt must still tell the
    model to refuse with a natural-language explanation (R2.1-fix Fix 2)."""
    out_zh = render_answer_prompt([], lang="zh")
    out_en = render_answer_prompt([], lang="en")
    assert "目前的資料裡沒有提到" in out_zh
    assert "doesn't mention" in out_en
    # No `[1]` source listed under the Sources header.
    assert "[1]\n" not in out_zh.split("Sources:")[-1]


def test_zh_prompt_snapshot():
    out = render_answer_prompt(_FIXTURE_CHUNKS, lang="zh")
    assert out == _EXPECTED_ZH


def test_en_prompt_snapshot():
    out = render_answer_prompt(_FIXTURE_CHUNKS, lang="en")
    assert out == _EXPECTED_EN


_EXPECTED_ZH = """你是 podcast 問答助理。請優先依據下方 sources 回答；回覆語言與使用者問題語言一致。

Citation 規範：
- 每一句陳述事實的句子，句尾請加上對應 source 編號 token，例如 `[1]` 或 `[1,3]`。
- 編號必須在 1..N 範圍內；不在範圍的編號後端會 strip 掉。

Faithfulness 規範：
- 具體事實點（人名、數字、地點、時間、引述原話）必須來自 sources，不得杜撰。
- 可以對 sources 做語意彙整、合理推論主旨，不必每個字都直接複製。
- sources 只給片段資訊時，請把已知部分講清楚並說明哪部分尚無資料，不要整段拒答。

拒答規範：
- 當 sources 完全無法支撐問題時，用自然中文回應，例如：「目前的資料裡沒有提到 X，建議用其他關鍵字試試。」（請把 X 換成問題實際在問的主題詞）。

回應格式：
必須是合法 JSON object：{"answer": "<你的回答（含 [N] / [N,M] token）>", "used_chunk_ids": ["ep:<episode_id>@<start_time>" 或 "desc:<episode_id>", ...]}
`used_chunk_ids` 只列出實際引用的 source 編號對應的 key。

Sources:
[1]
迪拉胖第一次來上節目時聊到童年。

[2]
他在 EP2 又補充了相關背景。

[3]
本集介紹了三首歌單。
"""


_EXPECTED_EN = """You are a podcast Q&A assistant. Prefer answering from the sources below; reply in the user's question language.

Citation rules:
- End each factual sentence with the matching source token, e.g. `[1]` or `[1,3]`.
- Numbers must be within 1..N; out-of-range tokens are stripped server-side.

Faithfulness rules:
- Concrete facts (names, numbers, places, times, direct quotes) must come from sources — never invent them.
- You may synthesise themes and infer main points across sources without quoting verbatim.
- When sources only give partial info, state what is known and flag what is missing — do not refuse outright.

Refusal:
- If no source can support the question, reply naturally, e.g. "The provided material doesn't mention X — try a different keyword." (replace X with the actual topic the user asked about).

Response format:
Must be a valid JSON object: {"answer": "<your answer with [N] / [N,M] tokens>", "used_chunk_ids": ["ep:<episode_id>@<start_time>" or "desc:<episode_id>", ...]}
`used_chunk_ids` lists only the source keys you actually cited.

Sources:
[1]
迪拉胖第一次來上節目時聊到童年。

[2]
他在 EP2 又補充了相關背景。

[3]
本集介紹了三首歌單。
"""
