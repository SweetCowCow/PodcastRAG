## Context

PodcastRAG 已上線一個多月，prod 累積 354 集 transcripts、180,826 transcript chunks（1536-dim OpenAI embedding）、162 集 episode descriptions（RSS metadata，全 show 100% 覆蓋）。當前 retrieval 是純 pgvector 餘弦相似度 top-K=8，R1.2 跑出來 Recall@5 = **2.4%**（lenient ±10s skip-judge）。Cross-episode aggregation 題型 10 題裡 8 題完全 0 分，code-switch / comprehension / negative 也都接近 0。

R1.2 的 48 題 golden set + judge bake-off + run.py 都已建好，eval 重跑只要 `python -m backend.eval.runners.run --dataset ... --backend-url https://api.podcastrag.app` 一行。

Stakeholder：管理員（也是唯一 admin）。

Constraints：
- 不引 LlamaIndex / LangChain（黑盒 + 大依賴）—— 純 SQL + 既有 sqlalchemy stack
- 不重轉錄（diarization / 重新 ASR 留 T1）—— R3.1 只在現有 transcripts 上動
- 維持 OpenAI text-embedding-3-small（成本 $0.001/月，不是優化目標）
- 一次 backfill embedding 預算上限 $1（180K chunks × 50 tokens × $0.02/M ≈ $0.18）

## Goals / Non-Goals

### Goals
- Recall@5 從 2.4% 至少拉到 single-digit（譬如 8-15%），給 R3.2 一個能再優化的起點
- Cross-episode 題型至少有非零分數（目前 0%）
- Code-switch（中英混）至少有非零分數
- Description 進入 retrieval（節目主原文 entity 密度高，且能避開 ASR 錯字風險）
- 可隨時在 admin UI 加 entity 詞，~5 min 內生效

### Non-Goals
- LLM topic segmentation 標 intro/業配/outro 段（R3.2）
- 兩層檢索（episode-level → chunk-level，R3.2）
- 來賓 / 日期 / 主題 metadata filter（R3.3）
- ASR 錯字後處理（T1 範疇）
- Speaker diarization（要重轉 360 集，留 P2）
- 自動 OOV detection（每月掃新詞，留 R3.x 或運維 habit）

## Decisions

### Decision 1: Chunk 重切 = 5-10 segments + 30-60s + segment-gap 切點 + 前後 1 segment overlap

**選擇**：
- 累積 segments 直到滿足任一條件就切：`>= 10 segments` OR `>= 60s` OR `(>= 5 segments AND >= 30s AND 下一 segment gap > 1.5s)`
- 切完後，這個 chunk 的 `text` 欄位包含「**前 1 segment** + 中段 N segments + **後 1 segment**」的拼接（含 overlap）
- `segment_ids` 仍只記錄真正屬於這 chunk 的中段（用於 client 跳轉播放時間）
- `start_time / end_time` 用中段 segments 的真邊界（不含 overlap segment）

**Why**：
- 30-60s 範圍比舊「硬 60s 上限無下限」靈活，短 chunk 訊號量低（少於 30s 沒幾個 entity 不適合 embed）
- segment-gap 優先於硬時長 → topic 邊界保留得更自然
- Overlap 解決 query 落在 chunk 邊界時兩個 chunk 都拿不到完整 context 的問題（標準做法）

**Alternatives considered**：
- Sliding window（fixed stride）：實作簡單，但對自然 topic 邊界感知差
- LLM topic segmentation 切點：效果可能更好但要全 show 跑一次 LLM（$2-3），R3.2 才做
- No overlap：實作最簡，但 boundary recall 差

### Decision 2: Tokenizer = jieba + DB-stored 自訂詞典 + 啟動時載入

**選擇**：
- Python `jieba` library（`jieba.cut(text, cut_all=False)`）
- 自訂詞典存 `tokenizer_custom_terms` 表（term VARCHAR, weight INT default 100, source VARCHAR, created_at, created_by）
- App startup 時 query 全表 → 用 `jieba.add_word(term, weight)` 載入
- Admin 加詞後呼叫 reload endpoint → backend / worker process 重 query DB 重載 jieba
- Tsvector 不靠 PG 內建（PG 沒中文分詞），由 application 端 jieba 分詞後組成 `to_tsvector('simple', '空格分隔的詞 list')` 寫入 DB

**Why**：
- jieba 是中文分詞的工業標準，輕量、無外部依賴、Apache-2.0
- DB-stored 詞典讓非 dev 也能加詞（admin UI），不用每次 PR + redeploy
- `to_tsvector('simple')` 只做 lowercase + tokenize-by-space，不做 stemming（中文不需要）
- weight 預設 100 比 jieba 內建詞高，確保自訂詞優先

**Alternatives considered**：
- 寫死 code 內的 list：每次加詞要 PR，慢
- 用 PG 的 `pg_jieba` extension：要 build C extension，Zeabur PG image 無，自編 image 維運痛苦
- pkuseg / ckip-tagger：精度可能更高但 model 大、loading 慢、依賴重
- BM25Okapi 純 Python：效能比 PG tsvector 差，且要把整個 corpus 拉到 app 端跑，scale 不好

### Decision 3: RRF 在純 SQL 跑，k=60，pgvector + tsvector 兩路 ROW_NUMBER

**選擇**：
```sql
WITH semantic AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> :query_embed) AS rank_s
  FROM transcript_chunks
  WHERE <show_id filter + status='completed'>
  LIMIT 50
),
lexical AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(text_tsvector, :ts_query) DESC) AS rank_l
  FROM transcript_chunks
  WHERE <show_id filter + status='completed'>
    AND text_tsvector @@ :ts_query
  LIMIT 50
)
SELECT COALESCE(s.id, l.id) AS id,
       1.0/(60+COALESCE(rank_s, 999)) + 1.0/(60+COALESCE(rank_l, 999)) AS rrf_score
FROM semantic s
FULL OUTER JOIN lexical l USING (id)
ORDER BY rrf_score DESC
LIMIT :k
```

對 description chunks 跑同樣的 query → UNION 兩邊結果 → 對 RRF score 再排一次取 top-K。

**Why**：
- RRF (Reciprocal Rank Fusion) 是工業標準混合 retrieval 演算法，論文 k=60 是 sweet spot
- 純 SQL = 一次 query 完成，無 app-side 排序成本
- `ts_rank` 用 PG 內建 BM25-like ranking
- pgvector 限 top-50 + tsvector 限 top-50：上限保 query 預算 < 200 ms

**Alternatives considered**：
- 加權線性融合（`α * sim + (1-α) * bm25`）：要 normalize 兩邊分數，維運麻煩
- 後排序（先各取 top-50，app 端 RRF）：多一次往返 + 反序列化開銷
- LlamaIndex SubQueryEngine：黑盒、依賴重、和我們 sqlalchemy 不合

### Decision 4: Episode description 走另開表 + 同 retrieval 流程後 union

**選擇**：
- 新表 `episode_description_chunks (id, episode_id, text, text_tsvector, embedding, created_at)`
- 一集一 row（description 通常 < 1000 token，不切 chunk）
- HTML strip + 業配 boilerplate 規則式 strip（match「鼓勵贊助」「按讚訂閱」等樣式）
- Retrieval 時 transcript_chunks RRF query + description_chunks RRF query 各自跑，UNION 兩邊取 top-K=8
- 標記 source（`source: 'transcript' | 'description'`）讓前端 SourceCard 顯示來源

**Why**：
- 表分開：start_time 對 transcript chunks 才有意義，混表會讓 client 想播這段時拿到無效時間
- 同 RRF 流程：保持邏輯簡單，不必為兩種來源寫不同 retrieval
- 1-row-per-episode：description 短，切 chunk 沒意義且會稀釋分數

**Alternatives considered**：
- 混進 transcript_chunks 表（episode_id 用，start_time=null）：schema 髒、client query 條件多
- 只當第一層 filter（先用 description retrieval 篩 episode → 再 transcript 找 chunk）：兩層檢索是 R3.2 計畫
- 不索引 description：浪費 RSS 已存的 entity-rich metadata

### Decision 5: Migration = 一次性砍 transcript_chunks 重建

**選擇**：
- Alembic migration: `ALTER TABLE transcript_chunks ADD COLUMN text_tsvector tsvector` + GIN index
- 寫 standalone script `backend/scripts/rebuild_chunks.py`：
  - 讀全部 transcripts → 對 segments 跑新 chunk 邏輯（含 overlap）
  - 用 OpenAI embedding API batch（每 batch 100 chunks）embed
  - jieba tokenize → `text_tsvector = to_tsvector('simple', tokens.join(' '))`
  - 寫回 transcript_chunks（同 transcript_id 先 DELETE 再 INSERT）
- 此 script 在 prod 跑一次（30-60 min），結束後新 retrieval 立即生效

**Why**：
- chunk 邊界改了 + 加 overlap，舊 chunks 直接寫入 tsvector 沒意義（tsvector 屬於整個 text 的詞集）
- 雙寫期（舊 chunks 跟新 chunks 並存）retrieval SQL 邏輯複雜化，且 SCORE 不可比
- baseline 2.4% 也沒高到捨不得砍重來
- backfill 期間 query API 維持可用：DELETE + INSERT 在每個 transcript scope 內 transactional

**Alternatives considered**：
- 雙寫過渡（新表並行）：複雜度爆炸，雙倍儲存，retrieval 兩邊都要打
- Online migration（chunk by chunk）：worker 去做，~6 hr 完成，但要寫 progress tracking + 失敗 recovery
- 保留舊 chunks 做 fallback：retrieval 不知道打哪份，徒增複雜度

### Decision 6: 業配 boilerplate strip = 規則式 + admin 可加規則

**選擇**：
- 寫一個 `boilerplate_patterns: list[str]` 預設清單（譬如「鼓勵贊助」「按讚訂閱」「歡迎收聽下集」），每個 pattern 用 regex 匹配連續行
- Apply 在 description 寫進 `episode_description_chunks` 之前
- 之後若需要可改成 DB-stored（admin 可加）但**不在 R3.1 範圍**

**Why**：
- 業配段落會稀釋 entity 訊號（每集都重複的句子會在 BM25 裡得高分）
- 規則式對 podcast 業配的固定話術夠用
- 真要 LLM 標業配段，是 R3.2 topic segmentation 的範疇

### Decision 7: Eval 三輪對照

**選擇**：跑 R1.2 golden set（48 題）三次：
1. **Pre-R3.1 baseline**：當前 prod 跑（已有 = 2.4%）
2. **R3.1 deploy 後（seed dict 50-80 詞）**：rebuild 完跑
3. **R3.1 + 你 audit 一輪 dict 補充**：依 eval 失敗題反查 → 加詞 → 重新 tokenize 部分 chunks → 再跑

每輪存 `backend/eval/runs/r31-<phase>.jsonl`，差異報告寫進 release log v1.4 entry。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| jieba 分詞錯誤 → tsvector 髒 | seed 詞典涵蓋已知 entity；admin UI 補詞；eval-driven 迭代 |
| Description boilerplate strip 過度刪掉真內容 | 預設 pattern list 保守（只刪明顯重複話術）；rebuild script log 顯示每集 strip 比例，異常 > 50% 警告 |
| RRF k=60 對某些 query type 不是最佳 | k=60 是文獻 baseline；R3.2 可實驗 query-type-dependent k |
| 30-60s chunk 對短 segment 多的集（純對話）切太細 | 5 segments 最低門檻；測試集涵蓋多 host 對話節目 |
| Backfill 期間舊 retrieval 不可用 | rebuild script 每個 transcript 做 DELETE+INSERT 的 single transaction，外部讀的話會看到舊 OR 新（不會看到空），完成前舊 retrieval API 仍能用 |
| OpenAI embedding rate limit | batch=100，sleep 1s/batch，180K chunks 約 30-60 min，預算內 |

## Migration Plan

**Stage 1（schema + service code）**：
- Alembic migration：加 `text_tsvector` 欄位 + GIN index、新表 `tokenizer_custom_terms`、`episode_description_chunks`
- `backend/app/services/tokenizer.py` 寫完 + tests
- `backend/app/services/description_indexer.py` 寫完 + tests
- `backend/app/services/chunking.py` 加 overlap 邏輯 + tests
- `backend/app/services/rag.py::retrieve()` 改 RRF SQL + tests

**Stage 2（admin UI + seed 詞典）**：
- `backend/app/api/admin/tokenizer.py` CRUD endpoints
- `src/AdminPage.jsx` 新 TokenizerTab
- `backend/scripts/build_jieba_seed_dict.py` 撈 OOV 候選（50-80 詞）
- 你人工審 → 寫 seed JSON 進 DB

**Stage 3（backfill）**：
- Deploy stage 1+2 到 prod（retrieval 暫時還會跑舊邏輯，因為 tsvector 都是空的）
- 跑 `backend/scripts/rebuild_chunks.py` 在 prod backend container（zeabur service exec）
- 同時觸發 description 索引建立（python -m backend.scripts.build_description_index --all）
- 跑完後 rag retrieve() 自然切換到 hybrid（新欄位有值就走新 SQL）

**Stage 4（eval + 迭代）**：
- 跑 R1.2 eval 第一次 → 對照 baseline
- 看失敗題反查 → 加詞 → 重 tokenize 受影響 chunks
- 跑 eval 第二次 → 對照
- Release log v1.4 entry

**Rollback**：
- 完整 rollback：rebuild_chunks.py 跑舊邏輯（保留 ahead-of-time tag），ALTER TABLE drop 新欄位
- 局部 rollback（保 schema，回舊 retrieval）：rag.py::retrieve() feature flag → 走舊 pgvector-only SQL

## Open Questions

1. **Seed 詞典規模**：50-80 詞夠不夠 cover 三個節目的 entity？（先做，看 eval 失敗題型再決定）
2. **Boilerplate pattern list**：預設清單寫多保守？（先寫 ~5 個明顯話術，看 strip 比例 log 再調）
3. **Description chunks 也要 ts_rank weighting 嗎？**（譬如 description 比 transcript 信賴更高）— 先 1:1 平等對待，看 eval 結果再決定
