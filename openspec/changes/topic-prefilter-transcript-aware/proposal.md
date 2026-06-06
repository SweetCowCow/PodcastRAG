## Problem

`episode_finders.find_episodes_by_topic`（及 `_with_source`）的候選集選只比 `episodes.title_tsvector` + `episode_description_chunks.text_tsvector`，**完全不看 transcript chunks**。後果：當問題的答案只存在於逐字稿口述、而集數的 title/description 沒提到相關關鍵字時，正確的 GT 集選不進候選，agent 的 `search_with_topic_prefilter` 就 scope 到錯的集。

## Root Cause

候選集選的 `_TOPIC_SQL` 只有兩個命中來源（title tsvector、description-chunk tsvector），缺 transcript-chunk 來源。b23 案例：題「迪拉跟 Leo王 怎麼從不認識變成合作夥伴／第一次見面」，GT 在 EP107（`8b3d4c1d`）逐字稿；topic「迪拉 Leo王」對 title/desc 算 ts_rank，EP107 排不進候選，反而 EP144「Ft. Leo王」（標題命中）被選 → 答案集被漏掉。

## Proposed Solution

讓候選集選變 transcript-aware：在 `_TOPIC_SQL`（與 `find_episodes_by_topic_with_source` 用的對應 SQL）的候選來源新增一個 transcript-chunk EXISTS 子句——某集只要有任一 `transcript_chunks.text_tsvector` 命中 topic OR-tsquery，即納入候選（鏡像既有 `episode_description_chunks` 的 EXISTS 子句）。

**主案 A（lexical transcript tsvector EXISTS）**：最小改動、鏡像既有已驗證的 description-chunk pattern、零額外 LLM/embedding 成本。

**over-select 防護（必要）**：host token（如「迪拉」）非鑑別、在全 show 逐字稿極常見，naive OR-match 會把候選撐爆（記憶實證 uncapped 64 集稀釋）。因此 transcript-chunk 來源須限制：只在 topic 含 ≥2 個鑑別 token（沿用既有 stop-word / show-name 過濾後）時才啟用 transcript EXISTS，或對 transcript 命中以 `ts_rank` 排序取前 N 集 cap。確切防護參數在 design.md 定，apply 時以 b23（須選進 EP107）+ 既有 topic 題（候選集數不得暴增）雙向驗證。

## Non-Goals

- 不改 chunk 層召回（`retrieve_hybrid`）或 voyage rerank——已驗證 scope 到 EP107 後 GT chunk 排 3/18，chunk 層沒問題。
- 不做「routing 改走 full-show」——2026-06-06 prod 驗證已淘汰（full-show top-50 GT 全 miss，episode competition）。
- 不做語意向量選集（備案 B，見 design.md Alternatives）——較貴，僅在主案 A 防 over-select 後仍漏 EP107 時才評估。
- 不改 agent 的 tool 選擇邏輯（agent 仍可呼叫 `search_with_topic_prefilter`，只是其候選來源變廣）。

## Success Criteria

- b23 題經 transcript-aware 候選集選後，EP107（`8b3d4c1d`）**進入候選集**（可由 `/admin/diagnose/...` 或單元/整合測試驗證候選含 EP107）。
- 既有純 title/desc 命中的 topic 題（如「歌單」）候選集**不退步**：仍選到原本的集、候選集數不因 transcript 來源暴增（設一個合理上限，design 定）。
- 既有 `test_chat_agent_topic_prefilter.py` 與 episode_finders 相關測試全綠。

## Impact

- Affected code:
  - Modified: backend/app/services/episode_finders.py
  - New: backend/tests/test_episode_finders_transcript_aware.py
- Affected specs: chat-agentic-routing（修改 `find_episodes_by_topic` 候選集選 requirement，納入 transcript-chunk 來源）
