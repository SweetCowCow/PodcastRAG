## Why

PodcastRAG 目前已能轉錄音訊並儲存 `transcript_segments`，但尚未提供語意查詢能力。前端 `QueryPage.jsx` 的 Chat 與 Semantic Search 兩個分頁都跑在 `MOCK_*` 資料上，使用者無法真正針對節目內容發問。此 change 建立 RAG 查詢後端：對轉錄段落做 embedding、以 pgvector 檢索、再透過 LLM 生成帶引用的回答，同時支援 multi-turn 對話與後台模型切換，讓核心使用情境可用。

## What Changes

- 新增 `transcript_chunks` 表（`id, transcript_id, start_time, end_time, text, embedding Vector(1536), segment_ids uuid[]`）；刪除既有 `transcript_segments.embedding` 欄位（改由 chunks 承載）
- 轉錄 worker 在 `save_transcript` 成功後，新增 step：把 segments 以 3–5 句 / 30–60 秒為單位聚合成 chunks，呼叫 OpenAI `text-embedding-3-small` 批次取得向量後寫入 `transcript_chunks`
- 新增 `POST /shows/{show_id}/query` endpoint：收 `{ question, messages?: [{role, content}], mode: "chat" | "search" }`
  - `search` 模式：對 question 做 embedding → pgvector cosine top-K=8 filter by show_id → 回傳 chunks 原文 + 時間戳（不走 LLM）
  - `chat` 模式：走 Tier 2 RAG
    1. 若有 `messages`：用 Rewrite 模型把 `[history + question]` 改寫成自包含問題（首輪跳過）
    2. 對 rewritten question 做 embedding → pgvector top-K=8
    3. 以 system prompt 要求引用 → Answer 模型產生回答
    4. 回傳 `{ answer, citations: [{ episode_id, start_time, end_time, text }] }`
- 新增「LLM 模型設定」DB 表（單列），儲存：`answer_base_url, answer_api_key, answer_model, rewrite_base_url, rewrite_api_key, rewrite_model`；預設指向 Zeabur AI Hub（`https://hnd1.aihub.zeabur.ai/v1`）
- 新增後台 endpoints：`GET /admin/llm-config`、`PUT /admin/llm-config` 供前端 `AdminPage.jsx` 的 LLM 模型頁讀寫
- Multi-turn 記憶採前端 state 滑動視窗 5 輪，**不持久化到後端**（關頁面即消失）

## Non-Goals

- 不實作 reranker（cross-encoder）；僅在 `design.md` 留擴充點，等初期品質不足再提新 change
- 不做對話持久化（無 `conversations` / `messages` 表）；等未來加帳號系統再處理
- 不跨 show 查詢；所有檢索都 filter by `show_id`
- 不實作使用者身分驗證；後台 endpoints 暫以既有 session 管理方式保護（本 change 不擴充）
- 不在 query 時做 HyDE、MMR、query expansion 等進階檢索策略

## Capabilities

### New Capabilities

- `rag-query`: Transcript chunk 生成、embedding 索引、pgvector 向量檢索、LLM 回答生成（含 query rewriting 的 multi-turn）、可切換 LLM 後台設定

### Modified Capabilities

- `db-schema`: 新增 `transcript_chunks` 表與 `llm_config` 表；移除 `transcript_segments.embedding` 欄位
- `transcription-pipeline`: 轉錄成功後新增 chunk 聚合 + embedding 步驟作為 worker task 的延伸

## Impact

- Affected specs: `rag-query`（新）、`db-schema`、`transcription-pipeline`
- Affected code:
  - `backend/app/models/transcript_chunk.py`（新）
  - `backend/app/models/llm_config.py`（新）
  - `backend/app/models/transcript_segment.py`（移除 embedding 欄位）
  - `backend/alembic/versions/<new>_add_rag_tables.py`（新 migration）
  - `backend/app/services/embedding.py`（新）
  - `backend/app/services/chunking.py`（新，Whisper segments → chunks 聚合）
  - `backend/app/services/rag.py`（新，檢索 + rewrite + answer）
  - `backend/app/workers/tasks.py`（轉錄成功後追加 embed step）
  - `backend/app/api/query.py`（新，`POST /shows/{id}/query`）
  - `backend/app/api/admin.py`（新，LLM 模型設定 endpoints）
  - `backend/app/core/config.py`（新增 Zeabur AI Hub 預設值）
  - `backend/.env.example`（新增預設 base_url）
  - `src/QueryPage.jsx`（串接 `/shows/{id}/query`；Chat tab 滑動視窗 5 輪）
  - `src/AdminPage.jsx`（LLM 模型頁串接 admin endpoints）
