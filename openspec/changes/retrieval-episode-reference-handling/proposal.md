## Problem

`/shows/{id}/search` endpoint 對含「EP X」episode-reference 的 query 系統性命中差。`multi-turn-40-add-recall-ground-truth` archive 跑出的 Recall@5 baseline = 0.2267 (n_scored=15)；deep_dive / cross_episode / multi-turn t1 題型 retrieval 多數 0 命中（譬如 b14「迪拉胖在 EP134 為什麼不挑振奮的開工歌」recall=0，b22「主持人陣容變化」recall=0，mt02/mt03/mt04 t1 全 0）。但 audit 階段用 keyword query 都找得到對應 chunks — GT 沒問題，是 query 撈不到。

## Root Cause

`public_search_show` 流程：query → embedding → `retrieve_hybrid`。沒有「query 含 EP 字串 → 抽 episode_id → 填 `episode_id_filter`」這層預處理。Embedding 對「EP134」字面相似度低（純數字 token 通用），BM25 對 transcript 文本內也罕見「EP134」字眼 — 所以撈到的多半是「迪拉」「開工」泛詞共現的 chunks，不是 EP134 內容。

對比：chat agent loop 內已有此能力（agent 看到 EP134 會先呼 `find_episode_by_ref` 抽 episode_id 再 `search_within_episode(episode_id=...)`）。所以 chat 路徑不受影響；只有 `/shows/{id}/search` public endpoint 沒這層 routing。`retrieve_hybrid` 函式本身早就支援 `episode_id_filter`，缺的是「在 endpoint 層偵測 EP-ref 並填它」。

## Proposed Solution

1. 新建 `backend/app/services/episode_ref.py`，提供 async helper `extract_episode_ids_from_query(db, show_id, query) -> list[uuid.UUID]`：
   - 用 regex（`r"EP\s*(\d+)"`，case-insensitive）抽出 query 內所有 episode number
   - 對每個 number N，跑 SQL `SELECT id FROM episodes WHERE show_id = :sid AND title ~ ('^EP' || :n || '(\D|$)')` 反查 episode_id（正則邊界避免 EP1 撈到 EP10 / EP143）
   - 沒命中的 number 跳過 + log warning（譬如 query 寫「EP999」但 show 沒這集）
   - 回 deduped UUID list，保留 query 內出現順序
2. 修改 `public_search_show` (`backend/app/api/query.py`)：embedding 取完後呼 helper；若回非空 list，用它 override `routed_eps`（兩層 routing default 已關，現況下不衝突；保留 fallback 是為了 user 顯式 enable routing 的 future case）。把結果填 `episode_id_filter` 傳 `retrieve_hybrid`。
3. Unit test 覆蓋 helper 行為（5 case）+ 整合 test 驗 endpoint 帶 EP-ref 時 retrieved hits 都在指定 episode。
4. Prod smoke：對 `extended-multi-turn-40.json` v2 重跑 `run_chat_agent_eval.py`，confirm `Recall@5` 從 baseline 0.2267 顯著升（success criteria: ≥ 0.40）+ 比對 per-turn 哪些 b14/b22/mt02/mt03/mt04 從 0 變正數。

## Non-Goals

- 不動 chat agent 內 tools（`find_episode_by_ref` + `search_within_episode` 已 work）
- 不處理中文 ordinal「第三集」之類 anaphora reference（屬 multi-turn carry / agent ordinal tool 範疇）
- 不調 RRF weight（episode-title weight 提升留另一個 change）
- 不對 non-EP-ref query 做任何 rewrite（譬如 guest_find「楊大正」仍走 metadata tool 路徑）
- 不刪 / 不動既有 two-layer routing 程式碼（已 default false 但保留 kill-switch）

## Success Criteria

- Unit test 5 個全綠（episode_ref helper 行為 + 邊界 case）
- 整合 test：mock `/shows/{id}/search` query 含「EP134」→ retrieved hits 全部 `episode_id == EP134_id`
- Prod smoke：對 `multi-turn-40.json` v2 重跑 eval，`Recall@5` ≥ 0.40（baseline 0.2267 → 目標 ≥ +18pp）
- b14 / b22 / mt02 t1 / mt03 t1 / mt04 t1 個別 turn recall 從 0 變 ≥ 0.5（這 5 題 GT 都明確在特定 EP）
- 既有 `test_chat_agent_loop.py` / `test_eval_runner_nested_recall.py` 等仍全綠（無 regression）

## Impact

- Affected specs: `rag-query`（MODIFIED — search endpoint 新增 EP-ref 預處理一條 requirement）
- Affected code:
  - New:
    - backend/app/services/episode_ref.py
    - backend/tests/test_episode_ref.py
  - Modified:
    - backend/app/api/query.py（`public_search_show` 加 helper call）
  - Removed:
    - 無
