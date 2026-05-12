## Problem

`r3-2-retrieval-fix` Phase 2 single-show pilot 跑完後（show `45fc2462-17cf-42f5-98a7-68fe1a222228` v1=163 + v2=2540 desc chunks 共存），final eval `backend/eval/results/eval-this-not-that-cool-20260512T023651Z.json`：

| 指標 | Phase 1 baseline | Phase 2 final | Δ |
|---|---|---|---|
| Recall@5 | 0.1548 | **0.0952** | **-0.0596（退步）** |
| MRR | 0.0833 | 0.0417 | -0.0416 |
| Judge mean | 0.4229 | 0.6354 | +0.2125 |

**Recall@5 退步 — Phase 2 gate FAIL**。Judge 上升但那不是 R3.2 gate（R3.2 gate 是 Recall@5 ≥ 0.35）。

源碼診斷後真因（詳見 `docs/case-studies/r32-routing-regression-2026-05-11.md` 2026-05-12 下午 section）：

1. **PG `ts_rank` 對短文本系統性壓低分數** — v2 短 chunk（44 字）對單 token query rank ≈ 0.0152；v1 整段（455 字）對同 query rank ≈ 0.0494（3.2× 差距）
2. **RRF_PER_SIDE=50 截斷把短 chunk 砍掉** — show 內 172 個 desc chunks 命中 q01 ts_query，EP1 v2 chunk_index=2（包含完美答案）排第 140 → 連 lexical CTE pool 都進不去
3. **`route_episodes` SQL（rag.py:293-301）沒 DISTINCT episode_id** — `LIMIT 10` 是 chunk-level 不是 episode-level。v1+v2 共存後 pool 從 163 → 2703，top-10 row 易被 4-5 個 episode 的 v2 短 chunks 佔滿，EP1 routing 出局 → retrieve_hybrid `episode_id_filter` 把 EP1 全部 chunks 鎖死在外
4. **`RAG_SHOW_NAME_FILTER=false` 對 q01 無感** 因為 (1)+(2) 結構性壓力：show-name token 留著只讓 v1 長段更容易吃光 lexical top-50 名額，反而讓 v2 短 chunks 更後面

簡單講：**v1 在共存 pool 裡用「整段密集 match」吃光 lexical top-50 + routing top-10 名額，v2 雖有精準答案但 rank 結構性弱，連 retrieval pool 第一關都過不了。**

`chunking-version-coexistence` design.md D3「retrieval 不過濾 chunking_version，靠 RRF score 自然決定」**錯估了 ts_rank 對長短文的 bias 強度**，也沒考慮 routing SQL `LIMIT 10 row != LIMIT 10 episode` 的放大效應。

## Proposed Solution

把 description-side retrieval 從「v1+v2 共池」改為「**同 episode 有 v2 就只用 v2，沒 v2 才 fallback v1**」，並修 routing SQL 的 episode-level dedup bug。

### 三個 SQL 改動點

1. **`_ROUTE_EPISODES_SQL`**：加 `DISTINCT ON (e.id)` + `WHERE e.id IN (SELECT episode_id WHERE chunking_version=2) OR no_v2_episode_id` 的 prefer-v2 邏輯（或 two-pass UNION：先撈 v2 top-K episodes，不足才補 v1）。確保 `LIMIT k` 是 k 個**不同 episode**，且優先用 v2 訊號
2. **`_DESC_RRF_SQL` / `_DESC_SEMANTIC_ONLY_SQL`**：semantic + lexical CTE 都加 prefer-v2 邏輯：`WHERE (d.chunking_version = 2) OR (d.chunking_version = 1 AND d.episode_id NOT IN (SELECT episode_id FROM episode_description_chunks WHERE chunking_version = 2))`。同 episode 有 v2 就只看 v2 chunks，沒 v2 才用 v1 fallback
3. **`ChunkHit` 已有 `chunking_version` 欄位**（chunking-version-coexistence 已加），retrieval 不需改 dataclass

### 為什麼修這條路而不是其他

| 候選 | 為什麼不選 |
|---|---|
| α' 治標：加大 `RRF_PER_SIDE` from 50 → 200 | ts_rank bias 還在；只是延後問題出現，全 show rollout 後仍會塞滿 |
| β' 改 ts_rank → ts_rank_cd | normalization mode 對長短文 bias 影響需另跑 lever 驗證，無法保證解決 routing 層問題 |
| γ' 換 embedding model | out of scope（R3.4），且不解 routing SQL `LIMIT 10 row` bug |
| **本方案：prefer-v2 結構性切換** | 直接消除「v1 v2 互卡」的根因；routing dedup 順手修；保留 v1 fallback 路徑安全 |

### In scope

1. `backend/app/services/rag.py`：改 `_ROUTE_EPISODES_SQL`（DISTINCT episode + prefer v2）、`_DESC_RRF_SQL`、`_DESC_SEMANTIC_ONLY_SQL`（prefer-v2 WHERE 子句）
2. 不動 transcript-side SQL（v1+v2 區分只存在於 description）
3. 單元測試：cover prefer-v2 行為（同 episode 有 v2 → v1 不入 pool；沒 v2 → v1 fallback）+ routing distinct
4. Re-run R3.2 Phase 2 final eval 跟之前 baseline 直接比；過 Recall@5 ≥ 0.35 才 ship
5. 更新 `chunking-version-coexistence` 已 archived 的 spec（記錄 D3 已被本 change 推翻）— 走 `openspec/specs/rag-query/spec.md` delta

### Out of scope

- 不換 embedding model（R3.4 改）
- 不改 RRF 融合算法本體（k=60 / per-side=50 不動，只動 WHERE）
- 不擴 golden set / 不換 judge model
- 不動 transcript-side retrieval
- 不執行 v1 cleanup CLI（仍留給 rollout 全完成後 ops 跑）

## Effort

- rag.py SQL 改動 + 推敲 prefer-v2 寫法：~1 hr
- 單元測試（≥ 4 個 fixture 場景）：~1 hr
- Phase 1 lever 驗證（pilot show 跑 1 次 eval，pre/post 比）：~30 min（含 v2.0 eval canary）
- Phase 2 final eval (v2.0 6-phase)：~1.5 hr
- 部署 + smoke + case study + release log：~30 min

**總計：~4.5 hr 開發 + ~2 hr eval = ~ 7 hr scope**

## Ship 標準（gate）

本 change 用兩分支 gate（詳見 design.md D6）：

1. Single-show pilot eval (show 「這又沒有很屌」, 48Q) **Recall@5 ≥ 0.30** — 跟 Phase 1 baseline 0.1548 比較 Δ ≥ +0.15（約 2x 提升）
2. Variance run（v2.0 eval 3 runs）SD ≤ 0.05
3. Judge mean ≥ 0.55（不退步於 Phase 2 0.6354 太多；CAP=0 仍 ship）
4. Latency P95 不爆（≤ 2500ms — 比 Phase 1 4350ms 不退步）
5. 單元測試覆蓋 prefer-v2 行為 + routing DISTINCT 各 ≥ 2 個 scenario
6. Prod smoke：`/shows/45fc.../search?q=節目名來源` 回傳含 EP1 hit（手測 sanity）

若 gate FAIL（Recall@5 < 0.30）：本 change 收尾紀錄結果，直接開下一張 change `r3-4-embedding-model-swap`（換 OpenAI text-embedding-3-large 或 multilingual-e5-large），R3.2 milestone 暫不 archive。

註：R3.2 原始 gate 是 Recall@5 ≥ 0.35。0.30–0.35 區間若達到，本 change ship 但 R3.2 milestone 不關（等 embedding swap 補尾才 archive）。

## Impact

- Affected specs：`rag-query`
- Affected code：
  - Modified：
    - `backend/app/services/rag.py`（3 條 SQL + 對應參數 binding）
  - New：
    - `backend/tests/test_description_retrieval_prefer_v2.py`
- Affected ops：
  - 本 change ship 後，「曼報」「壹加壹電台」rollout 仍按 `r3-2-retrieval-fix` Phase 2 staged 計畫進行；prefer-v2 邏輯不需要動其他 show（無 v2 自動 fallback v1）

## 依賴關係

```
chunking-version-coexistence  ──active（已 apply，schema + ChunkHit + indexer 已具備；等本 change ship 後一起 archive）
                ↓
r3-2-retrieval-fix Phase 2 pilot ──Phase 2 FAIL (Recall 0.0952)
                ↓ 真因 = 共池 ts_rank bias + routing dedup
description-retrieval-prefer-v2 ──本 change（這張）
                ↓ pilot Recall ≥ 0.30 ship（兩分支 gate）
r3-2-retrieval-fix Phase 2 rollout #2（曼報）→ #3（壹加壹電台）
                ↓
cleanup_v1_description_chunks.py per-show
                ↓
r3-2-retrieval-fix + chunking-version-coexistence 一起 archive + R3.2 milestone 收尾
```

本 change 卡 R3.2 milestone 收尾的第二道關。
