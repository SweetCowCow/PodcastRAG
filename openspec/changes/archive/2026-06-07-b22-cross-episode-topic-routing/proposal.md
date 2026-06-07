## Problem

跨集主題 / 跨集 narrative 類提問（例 b23：「迪拉跟 Leo王 是怎麼從不認識變成合作夥伴的？他們第一次見面的故事是什麼？」）在 chat agent 不會走 `search_with_topic_prefilter`——該工具會先 scope 到 topic 候選集、再 hybrid retrieve top-30 並做 voyage rerank，且候選集選已是 transcript-aware（change `topic-prefilter-transcript-aware` 已上線）。實測 agent 反而每次都選 `search_across_episodes`（全 show `retrieve_hybrid`、固定 k、不 scope、不 rerank）。

後果：b23 題的正確集 EP107 進不了候選/不被引用——full-show k=8 只撈到 1 個 EP107 chunk、被 bystander 集 EP116 主導 citations；且剛上線的 transcript-aware 集選完全不被觸發（dormant）。golden set `extended-multi-turn-40.json` 的 distributed-evidence 題（line 754 audit note）也記到同一 routing 問題「agent 走 search_across_episodes 未進 voyage rerank path，留待 b22 獨立 change」。

## Root Cause

已用源碼 + prod debug_trace 證據確認（非假說）：

- Agent loop（chat agent 主迴圈）呼 OpenAI 時用 `tools=OPENAI_TOOLS_SPEC` 搭 `tool_choice="auto"`，沒有任何 deterministic 預路由——工具選擇全交給 LLM 自由心證。
- 「跨集主題題優先用 `search_with_topic_prefilter`」這條指引只存在於 tool description（`search_across_episodes` / `search_with_topic_prefilter` 兩個 ToolSpec 的 description 文字，連例子都寫『迪拉跟 Leo 王 怎麼合作』），但 gpt-4o 忽略它。
- system prompt（chat agent prompts 模組）沒有任何 tool-routing 規則，只有 grounding / tool-eager / tool-error 規則。
- 工具語意比對：`search_across_episodes` callable = 全 show `retrieve_hybrid`（k、無 rerank）；`search_with_topic_prefilter` callable topic 命中時 scope 候選 + top-30 + voyage rerank、topic 無命中時 fallback 成與 `search_across_episodes` 等價的全 show retrieve。即前者是後者的子集行為。
- prod chat smoke（`backend/scripts/b23_prod_smoke.sh`，admin debug_trace，3/3 次）：b23 題 agent 全選 `search_across_episodes`，`search_with_topic_prefilter` 路徑（含 transcript-aware 集選）零觸發。

## Proposed Solution

加一層 deterministic 第一輪 routing nudge（鏡像 search-mode 既有的 deterministic gate 風格、以及既有 `enable_guest_dispatch` / `enable_transcript_topic_prefilter` 的 flag kill-switch 模式）：

- 偵測「跨集主題 / narrative」題型（高 precision、低 recall 取向，寧可漏判不可誤判）：非 episode-ref-scoped（沒指定 EP 編號 / 「這集」「上一集」）、且問題經 topic-term 抽取後有 ≥2 個鑑別 token。
- 命中時，**只在當輪 agent 的第一次 LLM call** 把 `tool_choice` 從 `auto` 改成強制 `search_with_topic_prefilter`；該工具回傳後，後續輪次恢復 `auto`，agent 仍可自由補呼其他工具。
- 不偵測命中、或 flag 關閉時，行為與現況位元等價（仍 `tool_choice="auto"`）。
- 新增 flag `enable_topic_routing_nudge`（預設 on，`ENABLE_TOPIC_ROUTING_NUDGE=false` 可不改 code 退回現況）。

因為 `search_with_topic_prefilter` 是 `search_across_episodes` 的嚴格超集（topic 無命中自動 fallback 同行為），強制走它對 topical 題是升級、對非 topical 題最差也只是退回等價行為，安全邊際高。

## Non-Goals

- 不刪 / 不退役 `search_across_episodes`：它被 `extended-multi-turn-40.json` 16 筆 `expected_tools` 依賴、且有 agent result mapper + tool registry 註冊，對真正無 topical scope 的跨集題仍是合法工具（退役 blast radius 太大，本 change 不取）。
- 不靠「在已飽和的 system prompt 疊更多 routing example」當主解（記憶實證：飽和 prompt 加 example 會 regress）；至多加一條精簡規則作輔助，主機制是 deterministic nudge。
- 不改 chunk 召回 / voyage rerank / `find_episodes_by_topic` 內部集選邏輯（那是 `topic-prefilter-transcript-aware` 的範圍）。
- 不改 search-mode（`mode="search"`）路徑，只動 agentic chat 工具路由。

## Success Criteria

- b23 題 prod chat smoke：agent 第一個工具呼叫為 `search_with_topic_prefilter`（非 `search_across_episodes`），且回應引用到 EP107 的初遇 / 合作 GT 段。
- 既有 `extended-multi-turn-40.json` 16 筆 `expected_tools=search_across_episodes` 的題，偵測器不誤判（不被強制改路由）——以 routing-only probe 列出每題偵測結果驗證。
- flag `ENABLE_TOPIC_ROUTING_NUDGE=false` 時，工具選擇與現況位元等價（單元測試：偵測命中題在 flag off 時 `tool_choice` 仍為 `auto`）。
- 既有 chat agent 相關單元測試全綠。

## Impact

- Affected specs: chat-agentic-routing
- Affected code:
  - Modified: backend/app/services/chat_agent/agent.py, backend/app/core/config.py
  - New: backend/app/services/chat_agent/routing.py, backend/tests/test_chat_agent_topic_routing_nudge.py
  - Removed: (none)
