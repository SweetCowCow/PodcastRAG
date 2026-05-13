## Problem

R3.2 (`r3-2-two-layer-topic-seg`) 2026-05-08 push、5/10 backfill 全 414 集跑完，5/11 第一次完整 baseline eval：

- Recall@5 (episode-level) = **0.1548**（48 題只 6.5 命中），target ≥ 0.35
- Recall@5 (chunk-level) = **0.0258**
- Judge mean = 0.4229（軟 gate ≥ 0.50 也沒過）

R3.2 gate 沒過 → 不能 archive；prod 端使用者搜尋命中率遠低於設計目標。

## Root Cause

第一輪歸因「two-layer routing 是兇手」**已證偽**：hotfix `ENABLE_TWO_LAYER_ROUTING=false` 完整 48 題 eval Recall@5 仍是 0.1548（與 flag on 一模一樣）。Hotfix flag 已從 prod 拔回；flag 邏輯保留在程式碼但 default 行為等同沒有 flag。

真兇候選有 5 個（按可能性序）：

1. `DESCRIPTION_CAP = 3` 把 top-5 灌滿 description hits — canary 觀察到 top-5 內常有 3 個 `@0.00`（描述塊）來自 3 個不同錯誤 episode
2. `show-name terms filter` 把 query 含 show name 的 lexical signal 完整 strip — DB 證實 `這又沒有很屌` 是 `is_show_name=true`，q01 lexical 側被掏空
3. Description embedding 顆粒太粗 — 每集 1 個 chunk，含贊助讀稿 + 摘要的長段，短句信號被平均化稀釋
4. Embedding model `text-embedding-3-small` 對中文短語 / 中英夾雜辨識偏弱 — `code-switch` 類 3/3 全 0% recall
5. RRF 融合不對稱 — transcript-side 與 description-side 各自 RRF 後 score 直接 sort 比較，缺乏 source-aware 重加權

候選 #1 和 #2 是「動 default constant」級別的低成本改動；#3 需要 re-chunk + re-embed backfill；#4 是換 embedding model 的大工程；#5 是結構重構。

## Proposed Solution

兩段式進行：

**Phase 1 — Lever test（快速篩真兇）**

加 2 個 env flag 短路最有可能的 2 個假設：

- `RAG_DESCRIPTION_CAP`（int，預設讀 `DESCRIPTION_CAP=3`；可設 0 完全停用 description hits）
- `RAG_SHOW_NAME_FILTER`（bool，預設 true；設 false 跳過 `_build_ts_query` 對 show-name terms 的 strip）

依序跑 4 組完整 48 題 eval（chunk-level + episode-level）：

| 組 | RAG_DESCRIPTION_CAP | RAG_SHOW_NAME_FILTER |
|---|---|---|
| (a) baseline | 3 | true |
| (b) 試 #1 | 0 | true |
| (c) 試 #2 | 3 | false |
| (d) 兩者皆動 | 0 | false |

把 (a→b) (a→c) (a→d) 的 delta 寫進 design.md evidence section。

**Phase 2 — 根因解（依 lever 結果分支）**

- **Case A**：(b) 或 (c) 單一組 Recall@5 ≥ 0.35 → 把該常數的 default 改成過 gate 的值（譬如 `DESCRIPTION_CAP=0` 或 show-name filter default false），ship
- **Case B**：(d) ≥ 0.35 但 (b) (c) 都沒過 → 兩個 default 都調整，ship
- **Case C**：(d) 仍 < 0.35 → 啟動 description chunking 細切（每段 ≤ 200 chars）+ re-embed backfill 全 414 集 description。此步驟成本估 ≤ $3，時間 ≈ 30 分鐘 backfill
- **Case D**：Case C 仍沒過 → 本 change 收尾「已盡 R3.x scope 內努力」紀錄結果，另開 `r3-4-embedding-model-swap`（不屬本 change scope）

**Final eval** 必走 `rag-eval-runner` skill v2.0 的 6 phase（preflight / canary 3 / metric-sanity / variance 3 runs / checkpoint / persistent runner）。

## Non-Goals

- 不換 embedding model（候選 #4 — 屬未來 change）
- 不動 two-layer routing 邏輯（已證偽，flag 機制留著但 default 行為照常）
- 不做 RRF 融合重構（候選 #5 — 結構重構，視 Case C 結果決定要不要另立 change）
- 不擴 golden set / 不換 judge model（R1.3 範疇）
- 不動 R3.3 metadata filter（已 parked，後續才做）

## Success Criteria

- 完整 48 題 baseline 跑出 episode-level Recall@5 ≥ 0.35
- Judge mean ≥ 0.45（軟 gate；若拉不回 0.50 但 retrieval 有明顯改善仍接受，比照 R2.1 軟 gate 處理）
- Phase 1 lever test 4 組數據完整寫進 `design.md` 與 `docs/case-studies/r32-routing-regression-2026-05-11.md`
- Final eval 走完 `rag-eval-runner` skill v2.0 的 6 phase 並有 variance SD ≤ 0.05 證據
- `r3-2-two-layer-topic-seg` 與本 change 可一併 archive（同 R3.2 milestone）

## Impact

- Affected specs: `rag-query`
- Affected code:
  - Modified:
    - `backend/app/services/rag.py`（加 2 個 env-flag 邏輯；視 Phase 2 結果改 `DESCRIPTION_CAP` default 或 show-name 處理路徑；Case C 時改 description chunker）
    - `backend/app/services/episode_description.py`（Case C 時細切邏輯，路徑視實際 chunker 位置調整）
  - New:
    - `backend/tests/test_rag_retrieval_flags.py`（2 個 env flag 行為 + Case C chunker 邊界）
  - Removed: 無
