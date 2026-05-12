## Context

`r3-2-retrieval-fix` Phase 2 single-show pilot 跑完後 Recall@5 從 0.1548 退到 0.0952。`chunking-version-coexistence` design.md D3 假設「v1+v2 同 RRF pool，靠 RRF score 自然決定」 — 經 prod DB 實測證偽：

對 show `45fc2462-...` 用 q01 等效 ts_query 跑 ranking simulation：

```sql
WITH ranked AS (
  SELECT d.id, ts_rank(d.text_tsvector, to_tsquery('simple', '節目名 | 這又沒有很屌 | 怎麼 | 來')) AS rank,
         ROW_NUMBER() OVER (ORDER BY ts_rank(...) DESC) AS rn
  FROM episode_description_chunks d JOIN episodes e ON e.id=d.episode_id
  WHERE e.show_id='45fc2462-...' AND d.text_tsvector @@ to_tsquery(...)
)
-- total match: 172
-- EP1 v1 chunk_index=0 (455 字整段): rn=1, rank=0.0494
-- EP1 v2 chunk_index=2 (44 字精準短句): rn=140, rank=0.0152
-- RRF_PER_SIDE=50 → EP1 v2 chunk_index=2 連 lexical CTE 都進不去
```

根因鏈：

1. `ts_rank` 短文 bias：v2 短 chunks rank 系統性低 3-4×
2. v1 大量湧入 `RRF_PER_SIDE=50` 上限，把 v2 擠出 pool
3. `_ROUTE_EPISODES_SQL` `LIMIT 10` 是 chunk-row level 不是 episode-distinct level（rag.py:293-301）— v2 共存後 pool ×16.5，routing top-10 容易塞滿 4-5 集
4. routing hard filter 把正確 episode 排除 → retrieve_hybrid 0 recall

詳見 case study `docs/case-studies/r32-routing-regression-2026-05-11.md` 2026-05-12 下午 section。

## Goals / Non-Goals

**Goals：**

- 把 R3.2 episode-level Recall@5 從 0.0952 拉到 ≥ 0.35（同 R3.2 設計 gate）
- 消除「v1+v2 同 pool ts_rank bias」結構性問題
- 修 `_ROUTE_EPISODES_SQL` 的 chunk-level vs episode-level 計數 bug
- 保留 v1 fallback：尚未 rollout 的 show（曼報、壹加壹電台）不受本 change 影響
- 與 `r3-2-two-layer-topic-seg` + `r3-2-retrieval-fix` 同一 R3.2 milestone 收尾

**Non-Goals：**

- 不換 embedding model（候選 ε / R3.4 範疇）
- 不改 RRF 算法（k=60, per-side=50 不動 — 改後本身能解決）
- 不動 two-layer routing on/off 邏輯（`ENABLE_TWO_LAYER_ROUTING` flag 留著）
- 不擴 golden set / 不換 judge model
- 不執行 v1 cleanup（cleanup CLI 在 rollout 全完後另跑）

## Decisions

### D1 — Retrieval 改成 prefer-v2（不是 filter-only-v2）

兩個方案：

**A. filter-only-v2**：retrieval SQL 加 `WHERE chunking_version = 2`，沒 v2 的 show / episode retrieval 結果空。
- 優點：簡單；不可能拿到 v1
- 缺點：尚未 rollout 的「曼報」「壹加壹電台」整 show 立刻沒 description hits → 退步使用者體驗

**B. prefer-v2 with v1 fallback**：retrieval SQL `WHERE (chunking_version = 2) OR (chunking_version = 1 AND episode_id NOT IN (SELECT episode_id WHERE chunking_version=2 AND show_id_filter))`。同 episode 有 v2 就只看 v2，沒 v2 才用 v1。
- 優點：rollout 各階段透明，無使用者體驗 cliff
- 缺點：SQL 稍複雜

**選 B**：本專案要 staged rollout，A 會在 rollout 過程中對未升級 show 造成體感退步。

### D2 — Prefer-v2 用 NOT IN 子查詢，不用 CASE WHEN

寫法選擇：

- `WHERE chunking_version = 2 OR episode_id NOT IN (sub-select v2 episodes for this show)` — PG 對小 sub-select 用 hash semi-join，性能可接受（show 內 episode_count ≤ 500，sub-select 結果集小）
- 不用 `CASE WHEN ... THEN ... ELSE` — 因為需要 join 自身，不適合 inline
- 不用 `LATERAL JOIN` — 同樣性能 OK 但讀起來複雜

具體 SQL pattern：

```sql
-- _DESC_RRF_SQL.semantic CTE
SELECT d.id AS chunk_id, ROW_NUMBER() OVER (ORDER BY d.embedding <=> ...) AS rank_s
FROM episode_description_chunks d
JOIN episodes e ON e.id = d.episode_id
WHERE e.show_id = :show_id
  AND d.embedding IS NOT NULL
  AND (
    d.chunking_version = 2
    OR (
      d.chunking_version = 1
      AND d.episode_id NOT IN (
        SELECT d2.episode_id
        FROM episode_description_chunks d2
        JOIN episodes e2 ON e2.id = d2.episode_id
        WHERE e2.show_id = :show_id AND d2.chunking_version = 2
      )
    )
  )
  {episode_filter}
LIMIT :per_side
```

同樣 pattern 套用 lexical CTE、`_DESC_SEMANTIC_ONLY_SQL`、`_ROUTE_EPISODES_SQL`。

### D3 — Route episodes 加 DISTINCT episode + prefer-v2

原本：

```sql
SELECT e.id AS episode_id FROM episode_description_chunks d
JOIN episodes e ... ORDER BY d.embedding <=> ... LIMIT :k
```

改成：

```sql
SELECT DISTINCT ON (e.id) e.id AS episode_id, d.embedding <=> :qv AS dist
FROM episode_description_chunks d JOIN episodes e ON e.id = d.episode_id
WHERE e.show_id = :show_id AND d.embedding IS NOT NULL
  AND (
    d.chunking_version = 2
    OR (
      d.chunking_version = 1
      AND d.episode_id NOT IN (SELECT episode_id FROM ... WHERE chunking_version = 2 AND show ...)
    )
  )
ORDER BY e.id, dist ASC
```

外層再用一個 wrapper 排序 + LIMIT k：

```sql
SELECT episode_id FROM (above_query) sub ORDER BY dist ASC LIMIT :k
```

確保 routing top-K 是 **K 個不同 episode**，且每個 episode 拿它自己最接近 query 的 chunk 當代表。

### D4 — 推翻 `chunking-version-coexistence` D3 假設

本 change spec delta 必須**明文記錄** `chunking-version-coexistence` D3 「retrieval 不過濾 chunking_version」假設已被 Phase 2 final eval 證偽，並用本 change 的 prefer-v2 邏輯取代。

`chunking-version-coexistence` 在本 change ship 後一起 archive（目前仍是 active change）；本 change 走 `openspec/specs/rag-query/spec.md` delta：MODIFIED 段落「`retrieve_hybrid` pools v1 and v2 description chunks together」要被本 change 的新 requirement 取代。

### D5 — Final eval 用 v2.0 6 phase

跟 `r3-2-retrieval-fix` D4 同步：preflight / canary 3 / metric-sanity / variance 3 runs / checkpoint / persistent runner。R2.1 archive RCA 教訓 — 單跑不認。

### D6 — Pilot 跑完 Recall@5 的兩分支判定

| 條件 | 行動 |
|---|---|
| Recall@5 ≥ 0.30 | ship；繼續 r3-2-retrieval-fix Phase 2 rollout #2（曼報）|
| Recall@5 < 0.30 | 不 ship；本 change 收尾紀錄結果；R3.2 milestone 暫不關；直接開 `r3-4-embedding-model-swap` change（換 text-embedding-3-large 或 multilingual-e5-large）|

註：R3.2 原始設計 gate 是 0.35；本 change 把 ship 門檻略降至 0.30（仍代表 Phase 1 baseline 0.1548 約 2x 提升）。R3.2 milestone 是否關取決於 0.35 是否到達 — 0.30-0.35 區間 ship 但 milestone 不關（等 embedding swap 補尾）。

## Implementation Contract

### Behavior

- `retrieve_descriptions(show_id, ...)`：對同一 show 內，凡是有 v2 chunks 的 episode，**只**回 v2 chunks；無 v2 的 episode 回 v1 chunks
- `route_episodes(show_id, ...)`：回 `k` 個**不同的** episode_id（不是 k 個 row）；偏好用 v2 訊號計算 cosine
- 完全沒 v2 chunks 的 show：行為等同 chunking-version-coexistence archive 前（純 v1 pool）
- 完全沒 v1 chunks（pilot 跑完 + cleanup）的 show：行為 = 純 v2 pool
- `ChunkHit.chunking_version` 仍存在不變

### Interface / Data Shape

- `_DESC_RRF_SQL` / `_DESC_SEMANTIC_ONLY_SQL` / `_ROUTE_EPISODES_SQL` 三條 SQL string 改寫；同 SQL params binding（無新 param）
- `retrieve_descriptions()` / `route_episodes()` Python signature 不動
- 無新 env flag — 行為純 SQL 邏輯切換（D1 選 B 後不需要 toggle）

### Failure Modes

- 子查詢的 v2 episode set 為空 → `NOT IN (空集)` PG 行為 = 所有 row 都通過 → 自動退化到純 v1 行為（如 chunking-version-coexistence 之前）
- 子查詢執行失敗（不應該發生，但保險）→ 整個 retrieve 失敗，由 API layer 500 處理
- 同 episode 有部分 v2 chunks 缺漏（譬如 pilot 中斷）→ pool 仍走 v2 path，但 fallback 不到 v1（這集所有 v2 chunks 都不夠精準時 retrieval 結果可能 0 hit）→ 由 rollout 流程「pilot 必須跑完所有 episode」保證避免

### Acceptance Criteria

- 新增單元測試 `backend/tests/test_description_retrieval_prefer_v2.py`：
  - Fixture: show A (episode E1 有 v1+v2, episode E2 只有 v1)，查 `retrieve_descriptions(show=A)`：
    - E1 結果只含 chunking_version=2 hits（無 v1）
    - E2 結果含 chunking_version=1 hits
  - Fixture: show B 完全沒 v2 → 行為等同舊（純 v1 pool）
  - Fixture: routing 對 show A (E1 v2 chunks ×10, E2 v1 chunks ×1) 跑 `route_episodes(k=2)` → 結果含 E1 + E2 兩個 distinct episode_id（不是 10 個 E1）
  - Fixture: 同 episode v2 多個 chunks 進 top-K → dedup 後不重複（沿用 chunking-version-coexistence 的 dedup_hits 邏輯）
- Pilot eval（show 「這又沒有很屌」, 48Q）Recall@5 ≥ 0.35，SD ≤ 0.05
- 三條 SQL EXPLAIN 看 hash semi-join 而非 nested loop（性能 sanity）
- Prod smoke `/shows/45fc.../search?q=節目名來源` top-5 含 EP1 hit

### Scope Boundaries

**In scope：**

- 改 `_DESC_RRF_SQL`, `_DESC_SEMANTIC_ONLY_SQL`, `_ROUTE_EPISODES_SQL`
- 新單元測試
- Single-show pilot eval + variance + smoke
- 更新 case study + release log
- `openspec/specs/rag-query/spec.md` MODIFIED requirements

**Out of scope：**

- 不換 embedding model（D6 才可能觸發另開 change）
- 不動 RRF 演算法 / k / per-side
- 不執行 cleanup v1（仍 deferred 給 rollout 完成後 ops）
- 不動 transcript retrieval / two-layer routing toggle
- 不動 indexer / migration / model schema

## Risks / Trade-offs

| 風險 | 嚴重性 | 緩解 |
|---|---|---|
| Prefer-v2 SQL `NOT IN` 子查詢拖慢 retrieval | 低 | sub-select 集合 ≤ episode count (per show ≤ 500)，PG hash semi-join 微秒級；本機 EXPLAIN ANALYZE 驗證 |
| Pilot Recall 仍 < 0.35 | 中 | D6 已寫處理路徑：< 0.20 不 ship；[0.20, 0.35] ship 並起 embedding swap |
| 推翻已 archive change 的設計（chunking-version-coexistence D3） | 低 | OpenSpec 允許 spec delta MODIFIED；docstring 補來龍去脈；歷史留紀錄不刪 |
| 同 episode 部分 v2 chunks 缺漏導致 fallback 不到 v1 | 中 | rollout 流程確保 pilot 100% 完成；resume state file 保證；本 change 不需特別處理 |
| Phase 2 final eval 仍未過 gate | 中 | 已寫進 D6；R3.2 milestone 不一定能本輪收尾 |
| EXPLAIN 顯示 PG 對 NOT IN 用 nested loop（規劃器 estimate 錯誤） | 低 | 可改寫 `WHERE chunking_version = 2 UNION ALL WHERE chunking_version = 1 AND episode_id NOT IN (...)` 強制 → 但先用 OR 寫法簡單；fallback 再改 |

## 跟 `r3-2-retrieval-fix` 的關係

這張等於 **r3-2-retrieval-fix Phase 2 retry**。前次 Phase 2 假設「re-chunk + re-embed + v1+v2 共池」夠了 — 證偽。本 change 用 prefer-v2 結構性切換補上 retrieval pool 設計缺口。

兩張共用 R3.2 gate (Recall@5 ≥ 0.35)；本 change pilot 過 gate 後 R3.2 milestone 走 r3-2-retrieval-fix Phase 2 rollout #2 / #3，再進 cleanup → R3.2 archive。

## 變更歷史

- 2026-05-12 propose：Phase 2 FAIL 後 forensic 診斷產出
