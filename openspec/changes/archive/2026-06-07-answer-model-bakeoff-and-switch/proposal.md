## Problem

Chat agent 的 answer step 目前用 gpt-4o（via AI Hub）。實測 gpt-4o 在餵完整 14 工具 spec 時**靜默忽略 forced `tool_choice`**（指定 function），回到自由選擇。後果：b22-cross-episode-topic-routing 的 D1 主機制（第一輪強制 `search_with_topic_prefilter`）在 prod 完全失效——agent 仍選 `search_across_episodes`，b23 的 transcript-aware 集選永不觸發。b22 已 park 在 5/6、卡在此問題無法收尾。

## Root Cause

已用對照實驗隔離（非假說），均經 AI Hub（`https://hnd1.aihub.zeabur.ai/v1`）+ 完整 14 工具 spec + 強制 `search_with_topic_prefilter`：

- **gpt-4o → 忽略**（3/3 自選 `search_across_episodes`）；**gpt-4.1-mini → 忽略**。
- **gpt-4.1 / gpt-5.1 / gpt-5.2 / claude-sonnet-4-6 / gemini-2.5-pro / gemini-2.5-flash / gemini-2.5-flash-lite / deepseek-* → 全部照辦**。
- **排除 context window**：prompt_tokens 僅 871–2742（離 gpt-4o 128K 上限兩個量級）；且 gpt-4.1 與 gpt-4o token 數一模一樣（1306）卻照辦 → 與 payload 大小無關。
- **排除 AI Hub proxy 整體 / design 問題**：同 proxy 同 spec 其他模型全 honor，機制本身正確。
- 對照下界：gpt-4o 在 1–4 個工具時會 honor forced tool_choice，工具一多（14）就不 enforce。結論為 **gpt-4o 單一模型的行為限制**（AI Hub 的 gpt-4o 可能為較舊 snapshot）。

## Proposed Solution

跑聚焦 bake-off 選一個會 honor forced tool_choice 且性價比好的 answer 模型，再切換：

- **候選**：gpt-4.1 / gpt-5.1 / gemini-2.5-flash / gemini-2.5-pro（皆已驗證 honor forced tool_choice）。
- **測試集**：代表性子集（~8–10 題），涵蓋 b23 跨集 + fact + comprehension + negative/refusal + multi-turn。
- **走 prod API**（每模型前改 prod DB `ai_steps.answer.model`，`get_step_config` 每 request 讀 DB → 即時生效、免 redeploy），每題每模型跑完整 agentic pipeline。
- **量四維度**：① 第一工具是否 = `search_with_topic_prefilter`（routing 驗證）② chunk_recall + factual（judge）③ 實際 in/out token × AI Hub 單價 = 每題真實成本 ④ 並排 dump 各模型答案供人工確認。
- Jacky 依結果拍板選定 → 把 prod DB `ai_steps.answer.model` 定為該模型 → 解鎖 b22（unpark + 跑 b23 prod smoke 收尾）。

因 `search_with_topic_prefilter` 是 `search_across_episodes` 嚴格超集，換模型只改「工具選擇是否被 enforce」與回答品質，不改 retrieval 行為。

## Non-Goals

- 不動 `rewrite` / `summary` / `topic_seg` step（均不使用 forced tool_choice，與本 bug 無關）。
- 不跑全 34 題、不跑 5-phase variance-baseline 回歸 eval（那是為偵測 prompt regression 微小 delta；本案是 4 模型挑一 + 看成本 + 看樣本，聚焦子集即可）。
- 不改 chunk 召回 / voyage rerank / `find_episodes_by_topic` 內部（屬其他 change）。
- 不改 b22 的 routing code（已完成、已部署、在會 honor 的模型上即生效）。

## Success Criteria

- 選定模型在 prod 用 `backend/scripts/b23_prod_smoke.sh` 跑 b23 題：agent **第一工具 = `search_with_topic_prefilter`**、回應引用 EP107。
- 選定模型在測試子集上的 factual / chunk_recall **不低於 gpt-4o baseline**（並排答案人工確認無明顯回歸）。
- bake-off 產出含每模型每題真實成本表 + total，作為決策依據留存。
- b22-cross-episode-topic-routing 解除 block（可 unpark 收尾 task 6）。

## Impact

- Affected specs: chat-agentic-routing
- Affected code:
  - New: backend/scripts/answer_model_bakeoff.py
  - Modified: (prod 資料變更，非程式碼) ai_steps.answer.model 由 gpt-4o 改為選定模型
  - Removed: (none)
