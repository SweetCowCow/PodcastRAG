## Problem

跨集 narrative 端到端題（b23：「迪拉跟 Leo王 是怎麼從不認識變成合作夥伴的？節目裡有提過他們第一次見面的故事嗎？」，GT = EP107 `8b3d4c1d`）在 prod 仍引用不到 EP107。2026-06-07 部署後 prod chat smoke ×6（answer 模型 gpt-5.1）：EP107 進候選 0/6、被引用 0/6，`prefilter_source` 全是 `topic_index`（非 `transcript_index`）。

這發生在前兩條 follow-up 都已上線之後：`topic-prefilter-transcript-aware`（transcript-chunk 候選來源）與 `topic-prefilter-hybrid-coverage-ranking`（hybrid union 排序，DB probe 證明同題下 EP107 #27→進 union）。也發生在 `b22-cross-episode-topic-routing` 的強制路由已部署之後——agent 第一個工具呼叫確實是 `search_with_topic_prefilter`（b22 force 生效），但仍救不到 EP107。

## Root Cause

已用源碼 + prod debug_trace 雙重證實（非假說）：

- `search_with_topic_prefilter` 工具 callable（chat agent tools 模組的 `_search_with_topic_prefilter`）呼 `episode_finders.find_episodes_by_topic_with_source(ctx.db, ctx.show_id, [inp.topic])` 時**只傳 `inp.topic`**；`inp.query` 只用在下游的 query embedding / `retrieve_hybrid` / voyage rerank，**完全沒進候選選集（episode 選擇）**。
- gpt-5.1 穩定把「實體」放 `topic`、把「敘述內容」放 `query`。prod 6/6 實測 `topic="Leo王"`（jieba 斷詞後鑑別 token `['Leo']` = 1 個）、`query="迪拉跟 Leo王 第一次見面、從不認識到合作夥伴的故事"`（鑑別 token 多）。
- `find_episodes_by_topic_with_source` 的 transcript-aware 候選來源觸發 gate 是「鑑別 token ≥2」。topic 只剩 1 個鑑別 token → gate 不開 → 走 `topic_index`（title/description tsvector 比對，只命中 EP7/EP144 等 4 集）→ **已部署的 transcript-aware 來源 + hybrid coverage 排序整個 dormant**，EP107 永遠進不了候選。
- 對照部署前 smoke：gpt-5.1 當時把整串「迪拉 Leo王 合作」塞 `topic`（3 token、gate 開），故路徑會觸發；今天穩定拆成單 token，路徑就死。模型在「topic vs query 怎麼拆」上會飄，端到端不能依賴 agent 剛好把足夠 token 放進 `topic`。
- b22 的 deterministic nudge 只改 `tool_choice`（強制走 `search_with_topic_prefilter`），不改 agent 生成的 `topic` 參數值，故對「thin topic-arg」這型無效。

→ 鑑別訊號（query）就在工具入參裡，只是沒被轉發進候選選集這一步。這是 b23 端到端三層（①routing 已通 / ②trigger 卡這 / ③ranking 已通）裡卡住的 ②-觸發層。

## Proposed Solution

把 `inp.query` 轉發進候選選集，讓 transcript-aware 來源的觸發 gate 與 token 推導在 topic 太薄時能用 query 的鑑別 token：

- `_search_with_topic_prefilter` callable 改為把 `inp.query` 一併傳入 `find_episodes_by_topic_with_source`（新增 optional 參數，不破壞既有 `find_episodes_by_topic` 呼叫點）。
- `find_episodes_by_topic_with_source` 在算 transcript-aware 路徑的鑑別 token 時：先用 topic 的鑑別 token；**當 topic 的鑑別 token < 2、且有提供 query 時**，改用 topic ∪ query 的鑑別 token（重用既有 `episode_finders._discriminating_tokens` 與 tokenizer expand 邏輯）。`topic_index`（title/desc）路徑與 guest-dispatch 不受影響（仍只用 topic）。
- 觸發後的 tsquery、`:tokens`（coverage arm）一律用這組「最終生效 token」，保持 D2 的「tsquery 與 tokens 同源」不變式。
- 受既有 flag `enable_transcript_topic_prefilter` 控制；query fallback 行為以既有 flag 涵蓋，不新增 flag（避免 flag 蔓延），但 design 須確認 flag off 時行為與現況位元等價。

## Non-Goals

- 不改 agent 怎麼生 `topic` / `query`（不動 prompt、不動 tool description 要求模型把更多字塞 topic）——記憶實證飽和 prompt 加 example 會 regress，且 deterministic 後端轉發比靠模型自律可靠。
- 不改 b22 的 routing nudge 機制本身（routing 已通）；b22 的 task 6 端到端「引用 EP107」半段會被本 change 修好，b22 archive 時其 task 6 應 re-scope 為 routing-only（與 `topic-prefilter-transcript-aware` task 5.1 同樣處理）。
- 不改 hybrid union 排序 SQL（③ 已 DB-proven）、不改 chunk 召回 / voyage rerank。
- 不改 `find_episodes_by_topic`（無 `_with_source` 後綴的舊 callable，給 `find_episodes_by_topic` 工具用）的簽章與行為。

## Success Criteria

- prod b23 smoke（部署後，`b23_prod_smoke.sh` 跑 ≥4 次）：EP107 進候選且被引用的命中率**明顯優於修前 0/6**（受 LLM 變異影響不要求 4/4，但須 >0 且 `prefilter_source=transcript_index` 確認 transcript 路徑有觸發）。這是 ①+②+③ 三層齊全後、長期卡住的 b23 端到端第一次該真的過。
- 既有 enumeration topic 題不回歸：DB probe 確認「高雄 美食」的 GT 主集 EP85、EP140 仍在候選、候選集數不暴增（query fallback 帶進的通用詞不得把既有題候選灌爆）。
- 既有 `test_chat_agent_topic_prefilter.py`、`test_episode_finders.py`、`test_episode_finders_transcript_aware.py` 全綠；新增單元測試覆蓋「query 轉發」與「topic 鑑別 token <2 時改用 query 鑑別 token 開 gate / 組 tsquery+tokens」與「topic ≥2 時不受 query 影響（行為不變）」。

## Impact

- Affected specs: chat-agentic-routing（修改 transcript 候選來源的觸發 gate token 來源：topic 薄時納入 query）
- Affected code:
  - Modified: backend/app/services/chat_agent/tools.py
  - Modified: backend/app/services/episode_finders.py
  - Modified: backend/tests/test_episode_finders_transcript_aware.py
  - New: (none)
  - Removed: (none)
