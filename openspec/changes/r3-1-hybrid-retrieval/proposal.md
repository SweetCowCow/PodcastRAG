## Why

R1.2 跑出來的 RAG baseline 是 **Recall@5 = 2.4%**（lenient ±10s skip-judge）— 對 162 集 podcast 而言，純語意檢索找對逐字稿片段的命中率不到 30 分之 1。Comprehension / cross-episode / code-switch 全部 0%。

三個結構性原因：(1) 中文 chunk 沒分詞，OpenAI embedding 對短中文 token 的訊號弱；(2) 節目主自創 entity（迪拉胖、顏色、顏社、台通…）embedding 抓不太到，但 BM25 關鍵字應該能；(3) RSS 已收錄全 162 集 `description`（餐廳列表、來賓、主題 bullets，entity-dense），純 transcript 檢索完全沒用到，且有時 description 比 transcript 還準（節目主原文 vs Whisper ASR 錯字「楓月食堂 / 蘴月食堂」）。

R3.1 把純 pgvector 換成 hybrid retrieval（pgvector + tsvector RRF 融合）+ chunk 重切（30-60s + 前後 segment overlap）+ jieba 自訂詞典 + episode description 進 BM25 索引，目標把 Recall@5 至少拉到 1 位數百分比，給後續 R3.2 / R3.3 一個能再優化的起點。

## What Changes

- **Chunk 重切（BREAKING：rebuild 全部 ~180K chunks，重 embed）**
  - 目前 5 segments OR 60s 硬切，無 overlap → 改成 5-10 segments（30-60s 範圍），優先在 segment 之間 gap 較大處切分
  - 每個 chunk 的 `text` 包含「前 1 + 中 5-10 + 後 1 segments」做 overlap context；`segment_ids` 仍然只記錄真正屬於這 chunk 的中段
- **新增 tsvector 欄位 + GIN index**
  - `transcript_chunks.text_tsvector` 由 application 端 jieba 預分詞後寫入（PG 沒內建 jieba）
  - 同時加 `embedding` ivfflat index（沿用既有）
- **新表：tokenizer 自訂詞典**
  - `tokenizer_custom_terms` 表（term, weight, created_at, created_by），seed 50-80 詞由腳本 + 人工審生成
  - Admin UI 新 tab 加詞 / 刪詞 / list / reload endpoint
- **新表：episode_description_chunks**
  - 一集一 row，存 cleaned description（HTML strip + 業配 boilerplate strip）+ tsvector + embedding
  - 與 transcript_chunks 同 RRF 流程後 union 排序
- **Retrieval SQL 從純語意改 RRF（純 SQL，不引 LlamaIndex/LangChain）**
  - pgvector top-50 + tsvector top-50 兩路，FULL OUTER JOIN，RRF score = `1/(60+rank_s) + 1/(60+rank_l)`
  - Top K=8 沿用既有 `RETRIEVAL_TOP_K`
- **Migration / backfill**
  - 一次性砍掉 transcript_chunks 全表重跑：新 chunk 邏輯 + jieba tokenize + OpenAI embed
  - Episode descriptions 也一次性 build 完
  - 預估執行 30-60 min（embedding API rate limit 是瓶頸；成本 < $0.30）
- **Eval 對照**
  - 跑 R1.2 golden set 三輪（baseline / R3.1-after / R3.1-after-with-dict-curation）對照 Recall@5 / MRR / 三類別 ratio
  - 結果寫進 release log v1.4 entry

## Capabilities

### New Capabilities

- `tokenizer-dictionary`: 自訂 jieba 詞典的 DB schema + admin 管理介面 + reload 機制
- `episode-description-index`: episode RSS description 進向量+BM25 索引，作為 retrieval 第二來源

### Modified Capabilities

- `rag-query`: chunk builder 改 overlap-aware 30-60s；retrieval 從純 pgvector 改 RRF (pgvector + tsvector) 融合；query 進 description chunks
- `db-schema`: `transcript_chunks` 加 `text_tsvector` 欄 + GIN index；新表 `tokenizer_custom_terms`、`episode_description_chunks`

## Impact

- Affected specs: `rag-query`（modified）、`db-schema`（modified）、`tokenizer-dictionary`（new）、`episode-description-index`（new）
- Affected code:
  - New:
    - backend/app/services/tokenizer.py — jieba 載入 + DB-stored 詞典 + tokenize helper
    - backend/app/services/description_indexer.py — episode description HTML strip + boilerplate strip + chunk build + embed
    - backend/app/models/tokenizer_term.py — `tokenizer_custom_terms` 表 model
    - backend/app/models/episode_description_chunk.py — `episode_description_chunks` 表 model
    - backend/app/api/admin/tokenizer.py — admin CRUD + reload endpoint
    - backend/app/schemas/tokenizer.py — request/response schemas
    - backend/scripts/build_jieba_seed_dict.py — 從 transcripts 撈 OOV 候選詞 → CSV 給人工審
    - backend/scripts/rebuild_chunks.py — 全表 rebuild：重切 + 重 embed + 重 tokenize
    - backend/tests/test_tokenizer.py
    - backend/tests/test_description_indexer.py
    - backend/tests/test_chunking_overlap.py
    - backend/tests/test_rag_rrf.py
    - backend/alembic/versions/<rev>_r31_hybrid_retrieval.py — schema migration
    - src/AdminPage.jsx — new TokenizerTab 元件（合併進 admin route）
  - Modified:
    - backend/app/services/chunking.py — 加 overlap + segment-gap 切點邏輯
    - backend/app/services/rag.py — retrieve() 改 RRF SQL，query 同時打 description_chunks
    - backend/app/services/embedding.py — 加 batch embed helper（rebuild script 用）
    - backend/app/models/transcript_chunk.py — 加 `text_tsvector` 欄位
    - backend/app/models/episode.py — relationship to episode_description_chunks
  - Removed: (none — 既有 pgvector retrieval logic 改不刪)
