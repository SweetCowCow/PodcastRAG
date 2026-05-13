## Problem

`r3-2-retrieval-fix` 五輪 lever test 跑完，episode-level Recall@5 結構性卡死在 **0.1548**：

| 組合 | Recall@5 | Δ vs baseline |
|---|---|---|
| (a) baseline | 0.1548 | — |
| (b) `RAG_DESCRIPTION_CAP=0` | ≈ 0.1548 | ~0 |
| (c) `RAG_SHOW_NAME_FILTER=false` | ≈ 0.1548 | ~0 |
| (d) (b)+(c) | ≈ 0.1548 | ~0 |
| (R3.2 5/12 sentinel sub-block) | 0.1548 | — |

`code-switch` 類 3/3 全 **0% recall**；`fact` 17.6%；`comprehension` 16.7%；都遠低於 R3.2 設計 gate ≥ 0.35。R3.2 design.md D3 條款明訂這個狀態觸發本 change：「Case D：本 change 不 ship；另開 `r3-4-embedding-model-swap`」。

真兇剩兩個候選：(4) **embedding model `text-embedding-3-small` 對繁中口語 + code-switch 信號吸收不足**、(5) RRF 融合不對稱（結構問題、另案）。本 change 攻 (4)。

## Root Cause（補 R3.2 lever 沒驗到的部分）

公開 benchmark + 我們的 sentinel cosine bake-off dry-run（`docs/research/embedding-bake-off-results-2026-05-12.md`）顯示：

- v3-small MTEB 62.3、v3-large 64.6（+2.3 絕對分）
- OpenAI 自評 MIRACL 多語 v3-large 比 ada-002 +6 pts
- 本 corpus baseline 0.1548 線性外推 v3-large 預估到 **0.17 - 0.22**（仍可能離 0.35 gate 有距離）

**單動 embedding model 不足以 100% 突破 ceiling**，因此本 change 同時打 (4) + 已被 R3.2 lever 證實有部分效果的 (3) description chunking 細切（200 → 120 chars），兩者合力。

## Proposed Solution

**Blue-Green embedding column swap**：

1. 加 `embedding_v2 vector(3072)` 欄位到 `transcript_chunks` + `episode_description_chunks` 兩張表
2. 加 ivfflat ANN index（lists=200 transcript / lists=50 description）
3. Backend code 改成「依 env flag `RAG_USE_EMBEDDING_V2` 決定讀 `embedding` 或 `embedding_v2`」
4. 寫入路徑同期雙寫（`EMBEDDING_DUAL_WRITE=true`），新 chunks 兩欄都填
5. `backend/scripts/backfill_embedding_v2.py` 全 corpus backfill（111k transcript + 3k description）
6. Description chunker max_chars 200 → 120，re-chunk description（chunks 數約增至 ~6,000）
7. `ai_steps` config 改 `text-embedding-3-small` → `text-embedding-3-large`
8. flip `RAG_USE_EMBEDDING_V2=true` → cutover
9. 跑 `rag-eval-runner` v2.0 6 phase final eval 驗 ship 標準
10. 觀察 7 天穩定 → cleanup migration drop `embedding` 舊欄位 + 舊 index

**Rollback** = flip `RAG_USE_EMBEDDING_V2=false`，< 30 秒回到 v3-small。

## Cost 估算

Corpus 規模（2026-05-12 DB 實測）：
- transcript_chunks: 111,441 筆，~80 tokens/chunk → ~8.9M tokens
- episode_description_chunks: 3,096 筆（細切後 ~6,000）→ ~0.9M tokens（含細切後增）
- 合計：**~9.8M tokens**

| 動作 | Cost |
|---|---|
| Sentinel bake-off（10 題對 743 chunks 兩個 model） | $0.015（dry-run 估，等 user 補 OpenAI key 才實跑） |
| Full corpus backfill `text-embedding-3-large` × 9.8M tokens × $0.13/M | **~$1.27** |
| Final eval 48 題 × 3 variance run × judge | ~$2.00 |
| **合計** | **≤ $3.50** |

對 OpenAI 餘額 $108.59（2026-05-12 baseline）影響 **≈ 3.2%**。

## Non-Goals

- 不換 provider（Cohere / Voyage / bge-m3 / Jina 全留 R3.5）
- 不改 hybrid retrieval / RRF 融合機制（另案）
- 不改 lexical（pg_jieba）side
- 不加 reranker（未來 R4.x）
- 不換 vector DB（pgvector 維持）

## Success Criteria

**必過 gate（ship 標準）：**

- 完整 48 題 final eval episode-level Recall@5 ≥ **0.25**（baseline 0.1548 的 1.6x）
- code-switch 類 Recall@5 ≥ **0.20**（從 0.00 拉起）
- variance SD ≤ 0.05（3 runs）

**加分 gate（過了同步 archive R3.2 milestone）：**

- 整體 Recall@5 ≥ 0.35
- Judge mean ≥ 0.55
- fact / comprehension 兩類各自 ≥ 0.25

**未過必過 gate 的處理**：本 change 不 ship、不 commit、保留 schema + 雙寫但 cutover env flag 不設、改開 `r3-5-bge-m3-hybrid-retrieval` proposal。

## Impact

- Affected specs: `rag-query`
- Affected code:
  - Modified:
    - `backend/app/services/rag.py`（讀 column 動態 + env flag）
    - `backend/app/services/transcription/embedding_step.py`（雙寫）
    - `backend/app/services/episode_description.py`（chunker max_chars 200→120）
    - `backend/app/services/embedding.py`（依 step config 切 model）
  - New:
    - `backend/alembic/versions/<rev>_add_embedding_v2_columns.py`
    - `backend/scripts/backfill_embedding_v2.py`
    - `backend/tests/test_rag_embedding_v2_flag.py`
    - `backend/tests/test_embedding_v2_dual_write.py`
    - `backend/tests/test_description_chunker_120.py`
- Affected data:
  - `transcript_chunks` ADD COLUMN `embedding_v2 vector(3072)` + ivfflat index
  - `episode_description_chunks` ADD COLUMN `embedding_v2 vector(3072)` + ivfflat index
  - `episode_description_chunks` 表中新 chunking_version 多一輪寫入（chunks 數約 +3000）
  - `ai_steps` embedding step config 行 UPDATE

## Pre-flight 證據（連到 research）

- `docs/research/embedding-model-bake-off-2026-05-12.md` — 10+ 候選 model 公開 benchmark 表 + prose；結論「OpenAI v3-large 進階段 2」
- `docs/research/embedding-bake-off-results-2026-05-12.md` — sentinel 小樣本 dry-run + cost + baseline 真實數字；候選 model API 執行待 user 補 OpenAI 直連 key 後一行指令補完
- `backend/eval/scripts/embedding_bakeoff.py` — bake-off script，dry-run 預設 + cost ceiling $0.20 + 自動覆寫 results

## Ship 標準（搬到一個段落方便檢查）

> **本 change ship 的 hard gate：完整 48 題 final eval `rag-eval-runner` v2.0 6 phase 跑完，episode-level Recall@5 ≥ 0.25、code-switch 類 Recall@5 ≥ 0.20、variance SD ≤ 0.05。任一未過 → 不 ship、不 commit、改開 R3.5 bge-m3 path。**
