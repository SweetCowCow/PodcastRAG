## 1. 資料模型與 Migration

- [x] 1.1 實作 Requirement: llm_config singleton table——在 `backend/app/models/llm_config.py` 新增 `LlmConfig` ORM 類（`id INT PK CHECK(id=1)`、`answer_base_url/api_key/model`、`rewrite_base_url/api_key/model`、`updated_at`）；於 `backend/app/models/__init__.py` 匯出
- [x] 1.2 實作 Requirement: transcript_chunks table for RAG retrieval——在 `backend/app/models/transcript_chunk.py` 新增 `TranscriptChunk` ORM 類（欄位依 design Decision 3），於 `backend/app/models/transcript.py` 的 `Transcript` 加 `chunks = relationship("TranscriptChunk", cascade="all,delete-orphan")`；同檔案維持既有 `segments` relationship
- [x] 1.3 實作 Requirement: transcript_segments table with pgvector（MODIFIED，移除 embedding 欄位）——在 `backend/app/models/transcript_segment.py` 移除 `embedding: Mapped[list[float] | None]` 欄位與 `from pgvector.sqlalchemy import Vector` import
- [x] 1.4 實作 Requirement: Alembic migration for RAG tables——`alembic revision -m "add_rag_tables"` 產新 migration：(a) `create_table transcript_chunks` 含 `segment_ids UUID[]`；(b) `create_index` ivfflat `vector_cosine_ops` `lists=100`；(c) `create_table llm_config` 含 `CheckConstraint("id = 1")`；(d) `op.execute("INSERT INTO llm_config (id, answer_base_url, answer_api_key, answer_model, rewrite_base_url, rewrite_api_key, rewrite_model) VALUES (1, 'https://hnd1.aihub.zeabur.ai/v1', '', 'gpt-4o', 'https://hnd1.aihub.zeabur.ai/v1', '', 'gpt-4o-mini')")`；(e) `op.drop_column("transcript_segments", "embedding")`；downgrade 路徑對稱
- [x] 1.5 `docker compose exec backend alembic upgrade head` 驗證 migration 成功；以 `\d transcript_chunks \d llm_config \d transcript_segments` 確認欄位；`SELECT * FROM llm_config;` 確認 seed 列存在

## 2. Chunk Builder 與 Embedding 服務

- [x] 2.1 實作 Requirement: Chunk builder aggregates Whisper segments——在 `backend/app/services/chunking.py` 新增 `build_chunks(segments: list[TranscriptSegment]) -> list[ChunkDraft]`：貪婪累積直到 `len>=5` 或 `current.end_time - first.start_time >= 60` 即 flush；剩餘也 flush；`ChunkDraft` dataclass 含 `start_time, end_time, text, segment_ids: list[uuid.UUID]`
- [x] 2.2 實作 Requirement: Chunk embeddings generated after successful transcription 的批次 embedding 工具——在 `backend/app/services/embedding.py` 新增 `embed_texts(texts: list[str]) -> list[list[float]]`：以 `openai.OpenAI(api_key=settings.openai_api_key)` 直接呼叫正式 endpoint（**不**走 Zeabur AI Hub）；按 64 筆為一批呼叫 `client.embeddings.create(model="text-embedding-3-small", input=batch)`；保留順序；對 `RateLimitError` 做 exponential backoff（最多 3 次）

## 3. Worker 整合（Requirement: Transcribe episode worker task 擴充）

- [x] 3.1 在 `backend/app/workers/tasks.py::transcribe_episode` 成功寫入 segments 後、`status=completed` 前，載入該 transcript 的 segments → `build_chunks()` → `embed_texts()` → 插入 `transcript_chunks`（批次 INSERT，單次 session commit），對應 `Scenario: Successful transcription`
- [x] 3.2 把 chunk 建立包在既有 transcript try/except 內；任何步驟拋例外時把 transcript 標 `failed`、`error_message` 取例外訊息 truncate 2000，對應 `Scenario: Embedding API failure fails the transcript` 與 `Scenario: Provider error`
- [x] 3.3 實作 `Scenario: Re-transcription replaces chunks`——重新轉錄前 `DELETE FROM transcript_chunks WHERE transcript_id = :tid`（在既有 segments 清理處同段執行）
- [x] 3.4 `backend/requirements.txt` 無需改動（openai / pgvector / sqlalchemy 皆已存在）；若 ORM array 型別需 `sqlalchemy.dialects.postgresql.ARRAY(UUID)` 確認 import 可用

## 4. LLM Client Factory 與 Config Service

- [x] 4.1 在 `backend/app/services/llm_config.py` 新增 `get_config(db) -> LlmConfig`（讀 `id=1` row，若空鍵 raise `LLMNotConfigured`）、`update_config(db, updates: dict) -> LlmConfig`（僅更新傳入欄位並 set `updated_at=now()`）
- [x] 4.2 新增 `get_answer_client(cfg)` 與 `get_rewrite_client(cfg)` factory：各自回 `OpenAI(base_url=cfg.*_base_url, api_key=cfg.*_api_key)`；model 字串另外回傳供呼叫端使用

## 5. RAG 服務（Requirement: Semantic search endpoint returns ranked chunks / Chat endpoint answers with citations using Tier 2 RAG）

- [x] 5.1 在 `backend/app/services/rag.py` 新增 `retrieve(db, show_id, query_embedding, k=8) -> list[ChunkHit]`：執行 design Decision 4 的 SQL（filter `show_id` + `status='completed'`、ORDER BY `embedding <=> :q` LIMIT k），回傳 `episode_id, episode_title, start_time, end_time, text, distance`
- [x] 5.2 新增 `rewrite_question(client, model, messages, question) -> str`：以 design Decision 6 的 Rewrite prompt 呼叫 `chat.completions.create`；取最近 10 則 history；回傳 rewritten 字串
- [x] 5.3 新增 `answer_with_chunks(client, model, messages, question, chunks) -> str`：以 design Decision 6 的 Answer prompt（含 chunks 內文與 `[ep:<id>@<time>]` 引用規範）呼叫 `chat.completions.create`；使用**原始** `question`，不用 rewritten 版
- [x] 5.4 sliding window 限制：在 `rewrite_question` 與 `answer_with_chunks` 入口以 `messages = messages[-10:]` 截斷，對應 `Scenario: Sliding window limit enforced`

## 6. Query API（Requirement: Semantic search endpoint / Chat endpoint）

- [x] 6.1 新增 `backend/app/schemas/query.py`：`QueryRequest(mode: Literal["chat","search"], question: str, messages: list[ChatMessage] = [])`、`ChatMessage(role: Literal["user","assistant"], content: str)`、`ChunkHit(...)`、`SearchResponse(results: list[ChunkHit])`、`ChatResponse(answer: str, citations: list[ChunkHit])`
- [x] 6.2 新增 `backend/app/api/query.py::POST /shows/{show_id}/query`：validate show 存在 → `mode=="search"` 走 `embed(question) → retrieve() → return results`（對應 `Scenario: Search returns top-K chunks from the specified show`、`Search excludes other shows`、`Search excludes incomplete transcripts`）
- [x] 6.3 Chat 分支：讀 `llm_config` → 若 api_key 空 raise HTTPException 400（對應 `Scenario: Missing API key rejects chat`）→ 若 `messages` 空跳過 rewrite（對應 `Scenario: First turn skips rewrite`）否則 `rewrite_question()` → `embed(rewritten)` → `retrieve()` → `answer_with_chunks()` → 組 `ChatResponse` 回傳（對應 `Scenario: Follow-up turn uses rewritten question for retrieval`、`Response includes citations`、`Updated config takes effect on next request`）
- [x] 6.4 於 `backend/app/main.py` 註冊 query router

## 7. Admin API（Requirement: LLM configuration is a singleton DB row）

- [x] 7.1 新增 `backend/app/schemas/admin.py`：`LlmConfigResponse`（api key 欄位固定為 `"***"`）、`LlmConfigUpdate`（全部欄位 Optional）
- [x] 7.2 新增 `backend/app/api/admin.py::GET /admin/llm-config` 與 `PUT /admin/llm-config`，對應 `Scenario: Config read via admin endpoint`、`Scenario: Config updated via admin endpoint`；mask 規則：回應中 `answer_api_key` 與 `rewrite_api_key` 一律以 `"***"` 取代實際值
- [x] 7.3 於 `backend/app/main.py` 註冊 admin router（尚未有身分驗證；先不加 middleware，未來 change 處理）

## 8. 前端整合

- [x] 8.1 `src/QueryPage.jsx`：把 Chat 分頁的 `handleSend` 改為 `POST /shows/{id}/query` mode=chat，body 附上 `messages: state.messages.slice(-10)`（最近 10 則）；收到 `{answer, citations}` 後 append 到 `messages` 狀態
- [x] 8.2 `src/QueryPage.jsx`：Semantic Search 分頁的 `handleSearch` 改為 `POST /shows/{id}/query` mode=search，渲染 `results` 為原 UI 形狀（epId + timestamp + text）
- [x] 8.3 `src/AdminPage.jsx`：LLM 模型設定頁在掛載時 `GET /admin/llm-config` 填表、存檔時 `PUT /admin/llm-config`；對 API key 欄位若顯示 `"***"` 且未被使用者修改則送出時**不帶**該欄位

## 9. 本地端到端驗證

- [x] 9.1 `docker compose build backend worker && docker compose up -d`；重跑 `alembic upgrade head` 確認 schema 已套用
- [x] 9.2 於 `docker compose exec db psql` 中 `SELECT count(*) FROM transcript_chunks;` 為 0；對先前 b89a4af2 episode 觸發一次 `POST /episodes/b89a4af2.../transcribe`，轉錄完成後再次 SELECT 應 > 0，且 `segment_ids` 非空、`embedding` 非 null
- [x] 9.3 在後台填入 OpenAI API key 至 `llm_config.answer_api_key` 與 `rewrite_api_key`（此時走 Zeabur AI Hub 的 OpenAI 相容路由，使用同一把 key）；`curl -X POST /shows/{show_id}/query -d '{"mode":"search","question":"…"}'` 驗證回 8 筆 chunks
- [x] 9.4 連續兩輪 chat：Turn 1 問 `"這集主要在談什麼？"`，Turn 2 帶 `messages` 歷史問 `"那第二點詳細點"`；檢查 Turn 2 回應合理引用、且 worker logs 顯示 Turn 1 僅 1 次 `chat.completions.create`、Turn 2 有 2 次（rewrite + answer）
