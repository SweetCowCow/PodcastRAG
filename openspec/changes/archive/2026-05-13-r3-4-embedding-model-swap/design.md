## Context

`r3-2-retrieval-fix` 五輪 lever test 證明：transcript-side retrieval 訊號層卡死在 Recall@5 = 0.1548，動 env flag / 常數都拉不動。R3.2 design.md D3 條款明訂這狀態觸發本 change。

預先研究產物：

- `docs/research/embedding-model-bake-off-2026-05-12.md`（公開 benchmark 比 10+ 候選 model）
- `docs/research/embedding-bake-off-results-2026-05-12.md`（10 sentinel × dry-run cost + baseline 真實 prod 數字 + 等使用者貼 OpenAI key 補完 v3-large 對照）
- `backend/eval/scripts/embedding_bakeoff.py`（dry-run 預設、cost ceiling $0.20、自動覆寫 results md）

候選 model 排名：

1. **text-embedding-3-large**（首選；本 change 採用）— API 完全相容、整合工作量最低、預估提升 +0.03 ~ +0.07 Recall@5
2. bge-m3（強候選但需 GPU/外部 inference；R3.5 才動）
3. Cohere / Voyage / Jina（不進此輪）

## Goals / Non-Goals

**Goals:**

- 把 episode Recall@5 從 0.1548 拉到至少 **0.25**（必過 gate），最好 ≥ 0.35（加分 gate = R3.2 原設計 gate）
- 把 code-switch 類 Recall@5 從 0.00 拉到 ≥ 0.20
- 替換策略採 blue-green，rollback path 是「flip env flag」（< 30 秒）

**Non-Goals:**

- 不換 provider（仍是 OpenAI；Cohere / Voyage / bge-m3 全留 R3.5）
- 不動 hybrid retrieval（transcript / description RRF 融合機制原樣）
- 不擴 golden set / 不換 judge

## Decisions

### D1 — 採 Blue-Green 替換策略（雙寫 + cutover env flag），不採 in-place

**選 Blue-Green**：新增 `embedding_v2 vector(3072)` 欄位 + ivfflat index → 雙寫過渡期 → backfill 全 corpus → env flag 切讀取側 → 觀察 1 週 → drop 舊欄位。

**理由**：
- Rollback 成本 = flip env flag（< 30 秒）
- 換 model 是「embedding space 完全改變」的破壞性變動，不可能 in-place（混 1536 + 3072 沒法 cosine 比較）
- 多花的儲存 ≤ 1.5GB 可接受
- 與 `chunking-version-coexistence` archive 留下的 pattern 完全對齊（已驗證可行）

**替代方案（不採）**：
- In-place（直接覆寫 `embedding` 欄位 + 改 dim）— rollback 等於 re-embed 全 corpus，不可接受
- 雙 model 雙寫永久共存 — 儲存成本 2x，無 ship 終點，無謂維護

### D2 — Embedding model 從 `ai_steps` config 切換，不寫死

prod 已有 `ai_steps` 表（`l0a1b2c3d4e5_add_api_keys_and_ai_steps.py` migration）儲存 embedding step config（key=`embedding`、value 含 model name + base_url + api_key reference）。本 change 只改 config row 從 `text-embedding-3-small` → `text-embedding-3-large`，**code 完全不寫死 model name**。

優點：未來換 model（譬如 R3.5 換 bge-m3）只動 config，不動 code。
副作用：alembic data migration 要小心 idempotency（不能盲改、要先 SELECT 再 UPSERT）。

### D3 — Dim 從 1536 → 3072，不採 Matryoshka 降維

OpenAI 允許 v3-large 用 `dimensions=1536` 參數降維到與 v3-small 同尺寸（保留 ANN index 不變）。**本 change 不採此路徑**，理由：

- 降維等同丟掉 50% 語意容量，本 change 的目的就是要拿到 v3-large 完整訊號
- ivfflat index rebuild 不貴（~10 分鐘，offline 跑完即可）
- 儲存增 2x 但絕對量 ≤ 1.5GB（Zeabur PG 容量充足）

### D4 — Ship gate 採軟硬雙閘

「必過」用較寬的 0.25（R3.2 baseline 的 1.6x），「加分」用原 R3.2 設計的 0.35。理由：

- 本 change 是 R3.2 ceiling 的 follow-up，**有實證證據（lever test）顯示單動作不太可能直接過 0.35**
- 0.25 必過 gate 已經是相對 +60% 提升，足以證明 swap 有效
- 0.35 加分 gate 觸發時可以同步 archive R3.2 milestone（一次收兩個 milestone）
- 0.25 必過但 0.35 沒到 → 仍 ship（embedding upgrade 不浪費）+ 觸發 R3.5

### D5 — 與 `description-retrieval-prefer-v2` 的關係

`description-retrieval-prefer-v2` 已 apply 並在 prod 跑著（commit `957cc9a`），但因 Recall < 0.30 gate 未過暫不 archive，等本 change 過 R3.2 gate 後一起 archive。其 retrieval 路徑優先讀 v2 chunks。本 change 在此基礎上：

- description chunker max_chars 從 200 → 120（更細）
- 細切後 v2 chunks 數會從 ~3,096 上升到 ~6,000
- 仍走 prefer-v2 邏輯，舊 v1 chunks 作 fallback
- `embedding_v2` 欄位**同時涵蓋 transcript_chunks 與 episode_description_chunks**（兩張表都加）

### D6 — Final eval 必走 rag-eval-runner skill v2.0 6 phase

沿用 R3.2 / R2.1 教訓：preflight → canary 3 → metric-sanity（派 sub-agent）→ variance 3 runs → checkpoint → persistent runner。不可單跑一次拿單一數字宣稱 ship。

## Implementation Contract

### Backend modifications

```
backend/alembic/versions/<rev>_add_embedding_v2_columns.py
  - ADD COLUMN transcript_chunks.embedding_v2 vector(3072) NULL
  - ADD COLUMN episode_description_chunks.embedding_v2 vector(3072) NULL
  - CREATE INDEX CONCURRENTLY ... USING ivfflat (embedding_v2 vector_cosine_ops)
  - data migration: UPDATE ai_steps SET config jsonb_set(...)
    （從 text-embedding-3-small 改 text-embedding-3-large）
  - downgrade(): DROP COLUMN + restore old ai_steps config

backend/app/services/rag.py
  - 加 module-level `_USE_EMBEDDING_V2 = os.getenv("RAG_USE_EMBEDDING_V2","false").lower() in ("true","1","on")`
  - 在每段 SQL 改成 `(:col_name :: regclass)` 形式或建 `_EMBEDDING_COL = "embedding_v2" if _USE_EMBEDDING_V2 else "embedding"` 動態組 query
  - dim 從 query embed 階段就要決定（讀 step config 取 model name 推 dim）

backend/app/services/transcription/embedding_step.py
  - 雙寫路徑：新 chunk insert 時同時補 `embedding` (legacy) + `embedding_v2` (new)
  - 若 step config 已切換到 v3-large，legacy 那欄寫 NULL 或保留 NULL fallback

backend/app/services/episode_description.py
  - chunker max_chars 200 → 120
  - boundary preserve heuristic 不變
  - 加 unit test 驗證

backend/scripts/backfill_embedding_v2.py
  - 沿用 backfill_topic_labels.py / pilot_reembed_descriptions.py pattern
  - --dry-run 預設 + cost estimate
  - --state-file checkpoint resumable
  - nohup-friendly（stdbuf -oL + python -u）
  - 處理兩張表（transcript + description）
  - rate limit guard（OpenAI tier 限制）
```

### DB schema delta

```sql
ALTER TABLE transcript_chunks ADD COLUMN embedding_v2 vector(3072);
ALTER TABLE episode_description_chunks ADD COLUMN embedding_v2 vector(3072);
CREATE INDEX CONCURRENTLY idx_transcript_chunks_emb_v2_hnsw
  ON transcript_chunks USING hnsw (embedding_v2 vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX CONCURRENTLY idx_desc_chunks_emb_v2_hnsw
  ON episode_description_chunks USING hnsw (embedding_v2 vector_cosine_ops) WITH (m=16, ef_construction=64);
```

**HNSW vs ivfflat 取捨（2026-05-12 user 拍板）**：pgvector 0.8.2 已支援 HNSW（since 0.5.0）。對 ~111k rows × 3072 dim，HNSW build 約 10 分鐘一次性、query recall 顯著 > ivfflat、latency 相當；index disk 約 2× ivfflat 但絕對量 < 1GB 可接受。預設參數 m=16, ef_construction=64 適合一般 retrieval。ef_search 走 query-time 設定（rag.py 設 40-80 視 top-k）。

### Env flags

| Name | Default | After cutover | Effect |
|---|---|---|---|
| `RAG_USE_EMBEDDING_V2` | `false` | `true` | Toggles `rag.py` read-side from `embedding` (1536) to `embedding_v2` (3072) |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| v3-large 對本 corpus 提升不如預期（< 0.25 必過 gate） | 中 | 高 | bake-off script 已備好，cutover 前先小樣本驗 + 觀察 canary 3；若小樣本 already 沒過 0.25 → 不做 backfill 直接觸發 R3.5 |
| Backfill 中斷（容器重啟 / API rate limit） | 高 | 低 | `--state-file` checkpoint + idempotent UPSERT；resumable |
| Cost 超 $5 ceiling | 低 | 中 | dry-run 預估 ~$1.22；hard guard `--force-budget` 才能超 |
| ivfflat index 重建期間 retrieval 慢 | 中 | 中 | `CREATE INDEX CONCURRENTLY`；分批 build；observation window |
| ai_steps config 改了但 backfill 沒跑完 → 新進 chunks 用 v3-large embed、舊 chunks 還在 v3-small → mismatch | 高 | 高 | 雙寫策略：backfill 完成前，寫入路徑同時補 `embedding` + `embedding_v2`，讀取路徑由 env flag 控制；config 切換**最後一步**才做 |
| Rollback 後資料殘留（embedding_v2 column 一直存在） | 低 | 低 | 觀察 1 週 + 確認 v2 穩定 → 跑 cleanup migration drop `embedding` + `idx_..._emb_cosine` |
| Prod retrieval 在 cutover 那一刻 outage | 低 | 高 | env flag 切換採 ramp-up（先設 10% traffic → 50% → 100%）— 但目前 backend 沒 traffic split 機制，因此採「凌晨切」+ canary watch 5 分鐘 |

## Scope Boundaries

**In-scope:**
- text-embedding-3-small → text-embedding-3-large（OpenAI 同家）
- description chunker max_chars 200 → 120
- embedding_v2 column / index / dual-write / cutover env flag
- ai_steps config row 更新
- 全 corpus backfill

**Out-of-scope（明確排除）:**
- Cohere / Voyage / bge-m3 / Jina（R3.5）
- 改 hybrid retrieval / RRF 融合（另案）
- 改 lexical（pg_jieba）side
- Reranker（如 Cohere Rerank、bge-reranker-v2）— 未來 R4.x
- Vector DB swap（pgvector → Pinecone / Qdrant / Weaviate）— 不評估
- Chunk metadata enrich（speaker / timestamp 加進 embedding 輸入）— R3.6 候選

## Open Questions（2026-05-12 user 拍板）

1. ~~ai_steps 切換時機~~ → **走 admin UI** 手動切，不寫進 alembic data migration（避免「config 已切但 backfill 沒做完」race condition）。流程：「backfill `embedding_v2` 全綠 → admin UI 切 ai_steps → 設 RAG_USE_EMBEDDING_V2=true 並 redeploy」。
2. ~~Embedding step config 是否需要 dim override~~ → **顯式寫 dim=3072 防呆**，避免未來 OpenAI 預設行為改變或誤改 step config 觸發 Matryoshka 降維。
3. ~~Rollback 後 embedding_v2 保留多久~~ → **1 個月觀察期**後跑 cleanup migration（章節 10）drop 舊 column + index + flag。

## D7 — routing 才是主因（2026-05-13 follow-up）

r3-4 cutover 後 prod eval：

| metric | LLM-auto-inflated 48-item set | human-curated 10-item set |
|---|---|---|
| Recall@5 | 0.2222 | 0.0625 |
| code-switch | 0.0 | 0.0 |
| fact | 0.353 | 0.0 |

r3-4 設計時假設 R3.2 ceiling (0.1548) 主因是 embedding model 訊號不足。2026-05-13 audit + spike 推翻這個假設：

- 移除 36 個 LLM-auto 壞題（壞題率 ≥75%）後，純人類 query 上 r3-4 的「fact +95%」消失（0.353 → 0.0），證明那是 LLM-auto-inflated 假象
- B3 spike：跳過 `route_episodes` 後 human-curated Recall@5 從 0.0625 → 0.4375 （7x）
- 真正瓶頸：`route_episodes` 在帶專有名詞 query 上把答案 episode 擋在 top-10 外

**結論**：
- **Embedding v2-large 維持 prod**（v3-large 對 fact 類仍有 marginal gain，且儲存成本可接受）
- 但 **r3-4 D4 ship gate 條件作廢** — Recall@5 ≥ 0.25 必過 / ≥ 0.35 加分 那組數字是建立在壞測試集上、不是 r3-4 該背的標準
- r3-4 archive 改以「embedding swap 不傷害、保留為未來基礎；真正的 retrieval quality gain 由 r3-5-disable-routing 達成」收尾
- 與 r3-5-disable-routing pair archive（同一輪 archive，順序 r3-5 先、r3-4 後）
- 後續 r3.x change 要設 gate 時 **必須以 human-curated 測試集為準**，不能再用 LLM-auto-inflated 數字

詳見 `openspec/changes/r3-5-disable-routing/design.md` D2-D6 段。
