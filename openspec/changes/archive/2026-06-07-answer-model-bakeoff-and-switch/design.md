## Context

Chat agent answer step（`ai_steps.answer`）現為 gpt-4o via AI Hub。b22 的 deterministic 第一輪 forced `tool_choice` 在 gpt-4o 上失效（gpt-4o 餵完整 14 工具 spec 時不 enforce forced function）。模型設定存 prod DB `ai_steps` 表，`ai_step_resolver.get_step_config` 每 request 讀 DB（非 env、非 build-time）。已驗證 gpt-4.1 / gpt-5.1 / gemini-2.5-flash / gemini-2.5-pro 在同 spec 下皆 honor forced tool_choice。

## Goals / Non-Goals

**Goals:**
- 用聚焦 bake-off 在 4 候選中選出「honor forced tool_choice + 性價比佳 + 回答品質不退」的 answer 模型。
- 把 prod `ai_steps.answer.model` 切到選定模型，解鎖 b22 收尾。
- 留下每模型每題真實成本 + 並排答案，作為決策與未來回顧依據。

**Non-Goals:**
- 不動 rewrite/summary/topic_seg step；不跑全集 variance-baseline 回歸 eval；不改 retrieval 內部；不改 b22 routing code。

## Decisions

### D1. Bake-off 方法（聚焦、非 5-phase）
- 候選 4 模型：gpt-4.1 / gpt-5.1 / gemini-2.5-flash / gemini-2.5-pro。
- 測試子集 ~8–10 題，從 `extended-multi-turn-40.json` 選，涵蓋：b23 跨集（routing 驗證）、fact、comprehension、negative/refusal、multi-turn 各 1–2。題目清單在 harness 內以 item id 寫死並於 design 記錄。
- 執行：對每個候選模型，先改 prod DB `ai_steps.answer.model`、再對 prod API（`https://podcastrag-api.zeabur.app`）以 e2e admin session + `debug_trace=true` 跑子集每題完整 agentic pipeline。
- 一次性 harness `backend/scripts/answer_model_bakeoff.py`，跑完自動把 `ai_steps.answer.model` 還原為起始值（fail-safe：harness 結束/中斷都還原）。

### D2. 選模準則（硬門檻 → 性價比 → 品質）
1. **硬門檻**：b23 題第一工具必須 = `search_with_topic_prefilter`（honor forced tool_choice）。不過門檻直接淘汰。
2. **回答品質**：子集 factual / chunk_recall 不低於 gpt-4o baseline；並排答案人工無明顯回歸。
3. **性價比**：每題真實成本（實測 in/out token × AI Hub 單價）。同等品質下取低成本。
- 最終由 Jacky 拍板（harness 只產數據與並排答案，不自動選）。

### D3. 切換機制
- 切換 = `UPDATE ai_steps SET model='<選定>' WHERE step_key='answer'`（prod DB）。`get_step_config` 每 request 讀 → 即時生效、**免 redeploy**。
- 不經 env、不改 code。

### D4. 量測與成本歸因
- 每題每模型從 `debug_trace` 取 `tool_calls[0].name`（routing 驗證）、citations（EP107 命中）、各 LLM round 的 prompt/completion token。
- 成本 = Σ(round) (prompt_tok × in單價 + completion_tok × out單價)；單價用 AI Hub 官方 per-M（2026-06-07 抓：gpt-4.1 2.00/8.00、gpt-5.1 1.25/10.00、gemini-2.5-flash 0.30/2.50、gemini-2.5-pro 1.25/10.00）。
- judge：用既有 `backend/eval` judge（factual / chunk_recall_grouped）對每題每模型評分。

### D5. Rollback / 安全邊際
- 切換是純資料變更，rollback = 把 `ai_steps.answer.model` 改回 gpt-4o。
- bake-off 期間 prod answer 模型會短暫輪換（低流量個人專案可接受）；harness 結束必還原起始值，避免遺留非預期模型。

### D6. 與 b22 的依賴
- 本 change archive（模型切定）後 → unpark b22 → 跑 `b23_prod_smoke.sh` 驗 routing 生效 → b22 task 6 收尾 → b22 archive。

## Implementation Contract

- **Behavior**：跑完 bake-off 後，prod `ai_steps.answer.model` 為 Jacky 選定且已驗證 honor forced tool_choice 的模型；b23 prod smoke 第一工具 = `search_with_topic_prefilter` 且引用 EP107。
- **Interface**：
  - 新 harness `backend/scripts/answer_model_bakeoff.py`：輸入候選模型清單 + 子集 item ids；輸出每模型每題 {first_tool, ep107_cited, prompt_tok, completion_tok, cost, factual, chunk_recall, answer 全文} + 彙總表；結束還原 `ai_steps.answer.model`。
  - prod DB `ai_steps.answer.model`：bake-off 期間輪換、結束還原；最終由人工定為選定模型。
- **Failure modes**：harness 中任何模型跑失敗 → 記錄該模型該題為 error、繼續其他、最後仍還原起始模型；不可遺留非起始模型在 prod。
- **Acceptance criteria**：
  - 4 模型 × 子集數據表（含成本 + factual + first_tool）產出並交 Jacky。
  - 並排答案 dump 供人工確認。
  - 選定模型 b23 smoke 過（first tool = prefilter + EP107）。
  - 選定模型子集 factual 不低於 gpt-4o baseline。
- **Scope boundaries**：in scope = bake-off harness + answer step 模型決策與切換 + 驗證。out of scope = 其他 ai_steps、retrieval 內部、b22 routing code、全集回歸 eval。

## Risks / Trade-offs

- **bake-off 期間 prod 模型輪換**：影響當下少量真實流量。緩解：低流量時段跑 + harness 結束必還原 + 每模型停留時間短。
- **子集代表性不足**：聚焦子集可能漏某些題型回歸。緩解：涵蓋 5 種 design_type；若選定模型上線後發現回歸，rollback 成本極低（改一個 DB 欄位）。
- **judge 成本/雜訊**：子集 + 單次評分有雜訊，但本案決策門檻是「不低於 baseline + 人工並排確認」，非偵測微小 delta，可接受。
