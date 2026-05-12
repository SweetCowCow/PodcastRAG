## Problem

`r3-2-retrieval-fix` Phase 1 lever test（4-arm × 48Q golden set，2026-05-12 跑完）證實 description embedding 顆粒太粗是 Recall@5 = 0.1548 結構性 ceiling 的真兇 — `RAG_DESCRIPTION_CAP=0` 把 description hits 全擋掉、Judge 從 0.42 跳到 0.63，但 Recall 動不了，因為每集只有 **一個** description chunk（贊助讀稿 + show notes + 重點 bullet 全平均化進去），嵌入向量訊號被稀釋。

Case C（Phase 2）必須 re-chunk 把每段切到 ≤ 200 chars + re-embed backfill。為避免「表現未穩定時對全 corpus 燒錢」，採**單節目 pilot →（這又沒有很屌, show_id `45fc2462-17cf-42f5-98a7-68fe1a222228`）→ 驗證 → rollout 其他節目**，預估 pilot ≤ $15。

**但 Phase 2 真的開跑前**有一個必要前置條件：DB schema 必須支援同表內 v1（舊整段）與 v2（細切）chunks **共存**。原因：

1. Pilot show re-chunk 後立刻刪 v1 會導致**其他 show 的 description retrieval 暫時不可用**（如果操作失誤誤刪）→ 不可接受
2. Pilot 結果若失敗，要能**單命令 rollback**（刪掉 v2，舊 v1 還在）→ 不可接受花時間 re-embed v1
3. Rollout 拉長到多個 show，期間 retrieval 必須**同時讀新舊版本**直到全部 show 都升到 v2，再統一刪 v1

目前 `episode_description_chunks` 在 `episode_id` 上有 `unique=True` → 一集只能有一個 chunk → v1+v2 共存技術上做不到，必須先動 schema。

## Proposed Solution

加 `chunking_version` smallint 欄位到 `episode_description_chunks`（且本 change scope 限 description chunks；transcript_chunks 未來若有同樣需求再另立 change），預設 v1，並把 `unique(episode_id)` 改成 `unique(episode_id, chunking_version)`，讓同一集可以同時有 v1（整段）與 v2（細切）多個 chunks。

`retrieve_hybrid` 的 description-side SQL **不過濾 chunking_version**（同時讀新舊版本進 RRF pool），但 `ChunkHit` 多帶一個 `chunking_version` metadata，讓 admin / monitoring / 下游 eval 可以觀察每次 retrieval 命中的是哪一版。

提供一支 idempotent CLI 腳本（**不在本 change 執行**，只設計 + 寫好留著用）讓 ops 在 rollout 全部完成 + final eval pass 後刪掉 v1 chunks，per-show 顆粒。

可選的監控：admin queue tab（或 `/admin/chunking-status` endpoint）暴露每個 show 的 v1 / v2 chunk 數比例，讓 ops 一眼看到 rollout 進度。

### In scope

1. DB schema：`episode_description_chunks` 加 `chunking_version smallint NOT NULL DEFAULT 1`；改 unique constraint
2. Alembic migration：欄位 + backfill 既有 row 為 1 + drop 舊 unique + add 新 unique
3. SQLAlchemy model：`EpisodeDescriptionChunk` 加欄位 + `__table_args__` 改
4. Retrieval (`backend/app/services/rag.py`)：description-side SQL 同時讀 v1+v2、`ChunkHit` 帶 `chunking_version`，預設給下游下文使用
5. Description indexer (`backend/app/services/description_indexer.py`)：寫入時帶 `chunking_version` 參數（預設 1，呼叫端傳 2 才寫 v2）
6. Idempotent v1 cleanup CLI 腳本（`backend/scripts/cleanup_v1_description_chunks.py`，per-show，dry-run default）— 設計 + 寫好但**不執行**
7. 單元測試：retrieval 對 v1+v2 混合 pool 行為、unique constraint 確實允許 (episode, v1) + (episode, v2) 共存、indexer 帶 version 寫對欄位
8. 可選 monitoring：`/admin/chunking-status` GET endpoint（per-show v1/v2 count），或先 SQL view 留著等 UI

### Out of scope

- 不寫實際 re-chunking 演算法（屬 `r3-2-retrieval-fix` Section 3 / Phase 2）
- 不執行 v2 backfill embedding（pilot 在 `r3-2-retrieval-fix` Phase 2 跑）
- 不擴 golden set / 不換 judge model
- 不動 routing 邏輯 / 不動 RRF 融合
- 不動 `transcript_chunks`（範圍只限 description；transcript 如未來要分版另立 change）

## Effort

- DB schema + migration：~20 分鐘
- 改 retrieve_hybrid + ChunkHit：~30 分鐘
- 改 description_indexer：~15 分鐘
- 寫 cleanup 腳本：~30 分鐘
- Monitoring endpoint：~30 分鐘
- 單元測試：~45 分鐘
- 寫測試 + 局部驗證：~30 分鐘
- 本機 + Zeabur 部署驗證：~30 分鐘

**總計：~3.5 hr 開發 + ~30 分 deploy 驗證 = 半天 scope**

## Ship 標準（gate）

1. Migration 上 prod 後，`SELECT chunking_version, COUNT(*) FROM episode_description_chunks GROUP BY 1` 全部回 `(1, N)` — 既有資料 backfill 對
2. 新增 unique constraint 允許同一 episode 寫入 (v1, v2) 兩 row（單元測試覆蓋）
3. 寫入一個 dummy (episode, v=2) chunk 後，`retrieve_hybrid` 對應 show 的 search 回傳結果中**有出現** chunking_version=2 的 hit（end-to-end 驗證）
4. 寫入 v2 chunk **不影響** 既有 v1 chunk 結果排序（比對 baseline + after 的 top-K episode set，至少 0.95 Jaccard）
5. 本 change 程式碼 push 後 production smoke：`/shows/{pilot_show}/search` 500-free，response shape 含 `chunking_version` 欄位
6. cleanup CLI 腳本 dry-run 印出將刪的 chunk count + episode list；**真實刪除留給 `r3-2-retrieval-fix` Phase 2 收尾後執行**
7. 所有新增單元測試（`backend/tests/test_chunking_version_coexistence.py`）綠

## Impact

- Affected specs：`rag-query`
- Affected code：
  - Modified：
    - `backend/app/models/episode_description_chunk.py`
    - `backend/app/services/rag.py`
    - `backend/app/services/description_indexer.py`
  - New：
    - `backend/alembic/versions/t8_*.py`（chunking_version migration）
    - `backend/scripts/cleanup_v1_description_chunks.py`
    - `backend/tests/test_chunking_version_coexistence.py`
    - （可選）`backend/app/api/admin/chunking_status.py`

## 依賴關係

- **Blocks**：`r3-2-retrieval-fix` Phase 2（必須先 archive 本 change 才能 pilot re-chunk + re-embed）
- **Depends on**：`r3-2-retrieval-fix` Phase 1（已完成）— Phase 1 lever 證實 Case C 才需要本 change
