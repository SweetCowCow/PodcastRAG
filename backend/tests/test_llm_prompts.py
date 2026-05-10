"""R2.1 section 2: snapshot tests for the answer prompt.

Catches accidental drift in the bilingual citation directive that R2.1's
faithfulness gate depends on. The snapshot is the rendered prompt for a
fixed three-source fixture, in both `zh` and `en`.

If a prompt change is intentional, regenerate the expected blocks below by
running `python -m pytest backend/tests/test_llm_prompts.py -k snapshot -s`
once and pasting the new output. Treat any unintended diff as a regression.
"""
from __future__ import annotations

from app.services.llm_prompts import (
    REFUSAL_TEXT,
    render_answer_prompt,
)


_FIXTURE_CHUNKS = [
    ("ep:e1@10.00", "EP1", "迪拉胖第一次來上節目時聊到童年。"),
    ("ep:e2@22.50", "EP2", "他在 EP2 又補充了相關背景。"),
    ("desc:e3", "EP3", "本集介紹了三首歌單。"),
]


def test_zh_prompt_contains_required_directives():
    out = render_answer_prompt(_FIXTURE_CHUNKS, lang="zh")
    # Numbered enumeration `[1] [2] [3]` (Decision 4 + spec scenario "Answer cites single source")
    assert "[1] ep:e1@10.00 (EP1)" in out
    assert "[2] ep:e2@22.50 (EP2)" in out
    assert "[3] desc:e3 (EP3)" in out
    # Bilingual refusal directive (spec scenario "Empty retrieval triggers explicit refusal in zh")
    assert REFUSAL_TEXT["zh"] in out
    # Single + multi citation forms documented
    assert "[N]" in out
    assert "[N,M,...]" in out
    # JSON shape unchanged (Task 2.3 — no breaking change to existing parser)
    assert '"answer"' in out
    assert '"used_chunk_ids"' in out
    # No-fabrication clause
    assert "不編造" in out or "不要" in out
    # Out-of-range refs are forbidden so the parser can strip them safely
    assert "1..N" in out


def test_en_prompt_contains_required_directives():
    out = render_answer_prompt(_FIXTURE_CHUNKS, lang="en")
    assert "[1] ep:e1@10.00 (EP1)" in out
    assert "[2] ep:e2@22.50 (EP2)" in out
    assert "[3] desc:e3 (EP3)" in out
    assert REFUSAL_TEXT["en"] in out
    assert "[N]" in out
    assert "[N,M,...]" in out
    assert '"answer"' in out
    assert '"used_chunk_ids"' in out
    assert "1..N" in out


def test_empty_chunks_still_renders_with_refusal_directive():
    """When retrieval returned zero chunks, the prompt must still tell the
    model to emit the bilingual refusal string (not fabricate)."""
    out_zh = render_answer_prompt([], lang="zh")
    out_en = render_answer_prompt([], lang="en")
    assert REFUSAL_TEXT["zh"] in out_zh
    assert REFUSAL_TEXT["en"] in out_en
    # No `[1]` source listed
    assert "[1]" not in out_zh.split("Sources:")[-1]


def test_zh_prompt_snapshot():
    """Frozen snapshot — change with intent only.

    Asserts the entire rendered prompt char-for-char so future drift is
    caught in code review (per task 2.4).
    """
    out = render_answer_prompt(_FIXTURE_CHUNKS, lang="zh")
    assert out == _EXPECTED_ZH


def test_en_prompt_snapshot():
    out = render_answer_prompt(_FIXTURE_CHUNKS, lang="en")
    assert out == _EXPECTED_EN


_EXPECTED_ZH = """你是 podcast 問答助理。只能根據下方提供的 sources 回答，sources 之外的事實一律不引用、不編造。
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
{"answer": "<你的回答（含每句末尾的 [N] / [N,M] token）>", "used_chunk_ids": ["ep:<episode_id>@<start_time>" 或 "desc:<episode_id>", ...]}

`used_chunk_ids` 只列出你實際引用的 source key（與下方 sources 區塊的前綴一致）。

Sources:
[1] ep:e1@10.00 (EP1)
迪拉胖第一次來上節目時聊到童年。

[2] ep:e2@22.50 (EP2)
他在 EP2 又補充了相關背景。

[3] desc:e3 (EP3)
本集介紹了三首歌單。
"""


_EXPECTED_EN = """You are a podcast Q&A assistant. Answer ONLY using the sources provided below; never introduce facts that are not in the sources.
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
{"answer": "<your answer with [N] / [N,M] tokens at the end of each factual sentence>", "used_chunk_ids": ["ep:<episode_id>@<start_time>" or "desc:<episode_id>", ...]}

`used_chunk_ids` lists only the source keys you actually cited (the prefixes shown in the Sources block below).

Sources:
[1] ep:e1@10.00 (EP1)
迪拉胖第一次來上節目時聊到童年。

[2] ep:e2@22.50 (EP2)
他在 EP2 又補充了相關背景。

[3] desc:e3 (EP3)
本集介紹了三首歌單。
"""
