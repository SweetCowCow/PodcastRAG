## 1. 設定旗標

> 對應 design D3「flag kill-switch」；spec requirement 的 `enable_topic_routing_nudge` 控制部分。

- [x] 1.1 在 `backend/app/core/config.py` 的 `Settings` 新增 `enable_topic_routing_nudge: bool = True`（鏡像 `enable_guest_dispatch` / `enable_transcript_topic_prefilter`，`ENABLE_TOPIC_ROUTING_NUDGE=false` 可關）。驗證：import settings 不報錯、欄位可由環境變數覆蓋（單元測試讀預設值通過）。

## 2. 偵測器

> 對應 design D2「偵測器：高 precision、低 recall」；spec requirement 的 detector 條件。

- [x] 2.1 新增 `backend/app/services/chat_agent/routing.py`，expose 純函式 `should_force_topic_prefilter(question: str) -> bool`：(a) 命中 episode-ref 樣式（`EP\d+` / `第\d+集` / 「這集」「上一集」「該集」等）→ 回 False；(b) 否則沿用 `episode_finders` 既有 topic-term 抽取（jieba → len≥2 → 去 `TOPIC_STOPWORDS` → 去 `tokenizer.get_show_name_terms()`）算鑑別 token 數，≥2 → True，否則 False；空 / 全 stopword 輸入 → False。實作 spec requirement 的 detector 行為（precision-over-recall、雙條件 AND）。驗證：單元測試——b23 題型回 True、含 `EP107` 或「這集」題回 False、單鑑別 token 題回 False、空字串回 False。

## 3. 第一輪 tool_choice 強制

> 對應 design「D1. Deterministic first-turn `tool_choice` 強制（主機制）」與「D4. tool_choice 套用點與 multi-turn 互動」；spec requirement「Cross-episode topical questions are deterministically routed to topic-prefilter search」的 force-first-call 行為。

- [x] 3.1 在 chat agent 主迴圈 `run_agent`（`backend/app/services/chat_agent/agent.py`）進 LLM 迴圈前算一次 `force_first = settings.enable_topic_routing_nudge and routing.should_force_topic_prefilter(question)`；迴圈第一輪（round index 0）當 `force_first` 為真時，OpenAI call 帶 `tool_choice={"type":"function","function":{"name":"search_with_topic_prefilter"}}`，其餘所有輪次維持 `tool_choice="auto"`。`force_first` 為假或 flag off → 所有輪次 `"auto"`（與現況位元等價）。實作 spec requirement「Cross-episode topical questions are deterministically routed to topic-prefilter search」的 force-first / revert-to-auto 行為。驗證：單元測試比對傳給 OpenAI 的 `tool_choice` 參數——偵測命中 + flag on → 第一輪為 forced function、第二輪為 auto；flag off 或未命中 → 第一輪即 auto。

## 4. 單元測試

> 對應 spec requirement「Cross-episode topical questions are deterministically routed to topic-prefilter search」全部 scenario 的 acceptance criteria。

- [x] 4.1 新增 `backend/tests/test_chat_agent_topic_routing_nudge.py`：涵蓋 detector（b23→True、EP-ref→False、單 token→False、空→False）與 `run_agent` 第一輪 `tool_choice`（命中+flag on→forced、命中+flag off→auto、未命中→auto、第二輪一律 auto），以 mock OpenAI client 攔截 call kwargs 斷言 `tool_choice`。驗證：pytest 該檔全綠。

## 5. Routing probe 校準（apply 時驗證偵測器不誤判）

> 對應 design D2 必驗項：標靶命中 + 既有 across_episodes golden 題不誤判。

- [x] 5.1 寫一次性 routing-only probe（可放 `backend/scripts/`），對 `extended-multi-turn-40.json` 16 筆 `expected_tools=search_across_episodes` 的題與 b23 題各跑 `should_force_topic_prefilter`，列出每題偵測結果：確認 b23 為 True、16 筆 across 題不被誤判為 True（若有少數命中，逐題判斷是否實為該走 prefilter 並在 design 記錄、或調整排除樣式 / 門檻後回填 task 2.1 與 design D2）。驗證：probe 輸出每題 question + 偵測結果 + 判讀；偵測器參數已定案。

## 6. 回歸與 prod smoke

> 對應 design Implementation Contract 的 acceptance criteria。

- [x] 6.1 跑既有 chat agent 相關單元測試確認無回歸（58 passed，含 `test_chat_agent_topic_routing_nudge.py` b22 偵測器/forcing 測試）；部署後（flag 預設 on）用 `backend/scripts/b23_prod_smoke.sh` 對 prod 打 b23 題 ×5（2026-06-07，commit 50ac924 後）：**agent 第一個工具呼叫 = `search_with_topic_prefilter` 5/5**（b22 deterministic force 直接交付，debug_trace `tool_calls[0].name`）、**回應引用 EP107 5/5**（「EP107｜迪拉的男團夢」初遇敘事）。**歸因註記**：b22 本身交付的是 routing force（強制走對工具，本 task 直接驗到）；「citations 含 EP107」這半段當初被 ②-觸發層 + ③-排序層卡住，是由 follow-up changes `topic-prefilter-transcript-aware`（候選來源）、`topic-prefilter-hybrid-coverage-ranking`（排序）、`topic-prefilter-forward-query-tokens`（query 轉發開 gate）三條補齊後才達成端到端。b22 是這條 narrative 題端到端鏈的第一環，現已與 ②/③ 層合流跑通。驗證：單元測試全綠 ✓；prod smoke first-tool=search_with_topic_prefilter 5/5 ✓ + citations 含 EP107 5/5 ✓（見 `topic-prefilter-forward-query-tokens/smoke-results.md`）。
