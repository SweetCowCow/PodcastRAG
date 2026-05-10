## Why

R2.1 上 prod 後（commit `68f9fa1` bilingual answer prompt with `[N]` citation contract），跑 mini-set eval 發現 judge mean 從 baseline 0.7146 掉到 0.5104（−0.2042）：
- 5/6 negative 題退步
- 14/17 fact 題退步 > 0.10
- 37/48 題 latency 翻倍（P95 2244 → 5531ms）

Root cause 已在 `docs/case-studies/r21-prompt-regression-2026-05-10.md` 完整剖析，4 條 fix 確認可挽回退步（Fix 1+2 估 +0.10，Fix 3+4 再 +0.10）。

| Pattern | 說明 | Fix |
|---|---|---|
| A — 過度拒答 | 「禁止編造」+「不確定就明說」雙重保險推 LLM 走拒答路徑 | Fix 3 |
| B — `[N]` 噪音 | answer 直接帶 `[1][2,3]` 給 judge，judge 看到不流暢字串扣分 | Fix 1 |
| C — Latency 翻倍 | system prompt token 暴增（~150 → ~450）+ chunks_block 多前綴 | Fix 4 |
| D — 機械拒答 | 固定字串「找不到相關內容，請改用其他關鍵字」judge 嫌不夠 contextual | Fix 2 |

## What Changes

1. **Fix 1 (rag.py)** — 加 `_CITATION_TOKEN_RE` 與 `strip_citations()` helper；`answer_with_chunks` 額外回 cleaned 版；eval runner 用 cleaned 版送 judge，前端拿 raw 保留 `[N]`。
2. **Fix 2 (llm_prompts.py)** — 拒答字串改自然中文範例：「目前的資料裡沒有提到 X，建議用其他關鍵字試試」（X 由 LLM 推論填入）。
3. **Fix 3 (llm_prompts.py)** — 「禁止編造」拆成多層：事實點來自 sources（人名/數字/地點/時間禁杜撰）/ 語意彙整 OK / 片段資訊給已有部分標明待補。
4. **Fix 4 (llm_prompts.py)** — 砍 prompt 長度：移除 `chunks_block` 的 `(episode_title)` 與 `source_key` 前綴 → 只留 `[N] {text}`；砍 inline example；zh/en 共用骨幹。

## Non-Goals

- 不改 judge prompt / rubric（屬未來範疇）
- 不改 retrieval 層（屬 R3.x）
- 不改前端對 `[N]` 的渲染邏輯（前端拿 raw `[N]` 保留）
- 不重新生成 ai_summary
- 不動 `REFUSAL_TEXT` 常數（測試 fixture 仍用，但 prompt 不再強制）

## Impact

- Affected code:
  - Modified:
    - `backend/app/services/rag.py`（加 `strip_citations` helper + `answer_with_chunks` 回 raw + cleaned）
    - `backend/app/services/llm_prompts.py`（Fix 2/3/4）
    - `backend/eval/runners/run.py`（`_query` 取 cleaned answer 送 judge；同步寫 `answer` 到 out_items 方便日後對照）
  - New:
    - `backend/tests/test_strip_citations.py`（unit test for helper + answer_with_chunks shape）
- Affected docs:
  - `docs/case-studies/r21-prompt-fix-eval-2026-05-10.md`（三輪數字對照）

## Success Criteria

1. Eval `judge_score_mean` ≥ 0.7146（baseline）才算過 gate
2. Latency P95 ≤ 3000ms
3. Negative judge ≥ 0.75
4. `/search` 或 `/query` API 對前端仍回含 `[N]` 的 raw answer
5. eval runner 送 judge 的 answer 不含 `[\d+]` 噪音
