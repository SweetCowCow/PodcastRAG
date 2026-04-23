## Context

`transcription-pipeline` 已能產出 `transcript_segments`（Whisper 的原始時間分段）。`transcript_segments.embedding Vector(1536)` 欄位在 `backend-api` 階段預埋但尚未使用。前端 `QueryPage.jsx` 已有 Chat（對話）與 Semantic Search（純搜尋）兩種 UI，目前全跑 `MOCK_*`。`AdminPage.jsx` 亦有 LLM 模型設定分頁，目前只是表單 mock。

pgvector 0.3.6 已安裝，extension 已 enable。OpenAI Python SDK 1.57.0 已安裝，後續可直接用它當 Zeabur AI Hub 的 client（base_url 切換）。

## Goals / Non-Goals

**Goals:**

- 在轉錄成功後自動產生可檢索的 chunks 與 embeddings
- 提供對話式與搜尋式兩種查詢 UX，皆 filter by show
- Chat 模式解決 follow-up 檢索漂移（query rewriting）
- 後台能切換 Answer 與 Rewrite 兩個 LLM，不重啟服務
- 使用 Zeabur AI Hub 為預設 LLM gateway，以便日後換 provider 不改 client code

**Non-Goals:**

- Reranker / cross-encoder：先不做，design 留擴充點
- 對話持久化：不做 `conversations` / `messages` 表
- 跨 show 查詢
- 使用者帳號系統 / 身分驗證強化
- 進階檢索策略（HyDE、MMR、query expansion）

## Decisions

### Decision 1：Chunk 粒度 — Whisper segments 滑動聚合

以 Whisper 轉錄的 `transcript_segments` 為輸入，按「連續 3–5 個 segments 或累計 30–60 秒」貪婪聚合成一個 chunk。用連續 segment 區間而不是固定字符切：

- Whisper segment 邊界通常是句子/停頓，聚合後保持語意完整
- 可精確保留 chunk 的 `start_time = first_seg.start`、`end_time = last_seg.end`
- 記錄 `segment_ids uuid[]` 作為 back-reference，前端需要時可還原到逐字稿對應段

聚合規則（由 `services/chunking.py:build_chunks(segments)` 實作）：

```
current = []
current_duration = 0
for seg in segments:
    current.append(seg)
    current_duration = current[-1].end - current[0].start
    if len(current) >= 5 or current_duration >= 60:
        yield build_chunk(current); current = []
# flush remainder
if current: yield build_chunk(current)
```

**為什麼**：3–5 句 / 30–60 秒是 podcast 單一論點的典型長度；過短（單 segment）embedding 語意薄，過長（>90s）檢索時細節被稀釋。

**Alternatives**：
- 固定字符切（500 chars）→ 會切到句子中間，時間戳失準
- 整集一個 chunk → 檢索無法定位片段
- Semantic chunking（用 embedding 判斷主題邊界）→ 實作複雜、本階段不需要

### Decision 2：Embedding 模型 — OpenAI `text-embedding-3-small`

固定使用 OpenAI `text-embedding-3-small`（1536 維），不做成後台可切換。批次呼叫 `embeddings.create(input=[texts], model="text-embedding-3-small")`，每批最多 64 chunks（OpenAI 單請求上限約 8192 tokens/2048 input，保守批量）。

**為什麼**：
- DB schema `Vector(1536)` 已固定，切換模型需 migration + 重建索引
- 中英混合 podcast 品質良好
- 成本極低（每小時 podcast ~ $0.0002）
- 走 OpenAI 正式 endpoint（**不**走 Zeabur AI Hub；AI Hub 主要定位是 Chat LLM gateway，embeddings 直接打 OpenAI 最穩）

**Alternatives**：
- `text-embedding-3-large`（3072 維）→ 品質提升邊際、儲存 × 2、本階段不必要
- 本地 BGE-M3（1024 維）→ 要改 schema + worker 載入 PyTorch model，成本不划算

### Decision 3：儲存 — 新表 `transcript_chunks`，廢棄 `transcript_segments.embedding`

```sql
CREATE TABLE transcript_chunks (
    id UUID PRIMARY KEY,
    transcript_id UUID NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,              -- 在 transcript 內的順序
    start_time DOUBLE PRECISION NOT NULL,
    end_time DOUBLE PRECISION NOT NULL,
    text TEXT NOT NULL,
    embedding vector(1536),
    segment_ids UUID[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (transcript_id, chunk_index)
);
CREATE INDEX ix_chunks_transcript ON transcript_chunks(transcript_id);
CREATE INDEX ix_chunks_embedding ON transcript_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

同時 `DROP COLUMN transcript_segments.embedding`（仍未寫入任何向量）。

**為什麼**：
- Chunk 層獨立於 segment 層，未來換 chunk 策略（如改字符切）不動原始轉錄
- `segment_ids` 保留回溯能力，前端逐字稿高亮用得上
- IVFFlat + cosine 為 pgvector 標配；`lists=100` 適合 <10 萬向量規模（一個 podcast show 百集 × 平均 30 chunks = 3000 vectors，遠低於此）

**Alternatives**：
- 沿用 `transcript_segments.embedding` → 被迫一 segment 一向量，embedding 太碎
- 另外一個向量 DB（Pinecone/Weaviate）→ 違反 architecture-decisions 的「不用外部向量 DB」

### Decision 4：Retrieval — pgvector cosine，top-K=8，filter by show_id

SQL 形式：

```sql
SELECT c.id, c.start_time, c.end_time, c.text,
       c.embedding <=> :query_embedding AS distance,
       e.id as episode_id, e.title as episode_title
FROM transcript_chunks c
JOIN transcripts t ON t.id = c.transcript_id
JOIN episodes e ON e.id = t.episode_id
WHERE e.show_id = :show_id
  AND t.status = 'completed'
ORDER BY distance
LIMIT 8;
```

**為什麼**：
- cosine 是文本 embedding 標配距離
- K=8 是 RAG 甜蜜點：chunks 合計約 2000–4000 tokens，塞進 LLM 還有餘裕給 history + prompt
- filter by show 對應 UX（使用者先選 show）
- `t.status = 'completed'` 避免 stale chunks 汙染結果

**Alternatives / 擴充點**：
- 加 reranker（cross-encoder 如 `BAAI/bge-reranker-v2-m3`）做二階段排序 → 品質不足再加；實作時保留 `rag.py:retrieve()` 回傳 top-K 後的 hook，不動 API 介面
- 調整 K → `rag.py` 保留可參數化，後台可放到未來再做

### Decision 5：LLM gateway — Zeabur AI Hub（OpenAI 相容），後台可切 Answer / Rewrite 雙模型

DB 新表 `llm_config`（單列 row，`id=1`）：

```sql
CREATE TABLE llm_config (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton
    answer_base_url VARCHAR(500) NOT NULL,
    answer_api_key TEXT NOT NULL,
    answer_model VARCHAR(200) NOT NULL,
    rewrite_base_url VARCHAR(500) NOT NULL,
    rewrite_api_key TEXT NOT NULL,
    rewrite_model VARCHAR(200) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

初始化 seed：

- `answer_base_url = rewrite_base_url = https://hnd1.aihub.zeabur.ai/v1`
- `answer_model` 初始預設 `gpt-4o`（由使用者在後台改）
- `rewrite_model` 初始預設 `gpt-4o-mini`
- `answer_api_key` / `rewrite_api_key` 允許相同字串；首次部署由使用者在後台填入

Runtime 用：

```python
def get_answer_client(cfg): return OpenAI(base_url=cfg.answer_base_url, api_key=cfg.answer_api_key)
def get_rewrite_client(cfg): return OpenAI(base_url=cfg.rewrite_base_url, api_key=cfg.rewrite_api_key)
```

每次 `/query` 呼叫讀一次 `llm_config`，不做全域快取（單列查詢成本低；這樣後台改完即生效）。

**為什麼**：
- Zeabur AI Hub 是 OpenAI-compatible，`base_url` 切換後 SDK 零改
- 單列 singleton table 比 env var 靈活：後台改完立即生效，無需重啟
- Rewrite / Answer 拆開讓使用者用小模型省 query-rewrite 的成本

**Alternatives**：
- 存 env var → 要重啟 worker/backend 才生效；多實例部署時難同步
- 多 provider（Anthropic/Google 直連）→ 目前 Zeabur AI Hub 已可代理，不需多套 SDK

### Decision 6：Multi-turn Tier 2 — 滑動視窗 5 輪，前端保存，query rewriting 首輪跳過

**前端**：`QueryPage.jsx` 的 `messages` state 在送查詢時取最近 10 則訊息（5 輪 user+assistant 配對），附到請求 body。

**後端 `/query` chat 模式流程**：

```
1. 取得 llm_config（一次 SELECT）
2. 若 messages 非空：
     rewritten_q = Rewrite LLM({system: rewrite_prompt, messages: [...history, {user: question}]})
   否則：
     rewritten_q = question  ← 首輪跳過 rewrite
3. query_embedding = OpenAI embed(rewritten_q)
4. chunks = pgvector top-8 filter by show_id
5. answer = Answer LLM({system: rag_prompt(chunks), messages: [...history, {user: question}]})
6. return {answer, citations: chunks}
```

**Rewrite prompt（hard-coded in code，雙語版）**：

```
You rewrite a follow-up question into a standalone question, preserving the
original intent and language. Use conversation history only to resolve
pronouns and implicit references. Output ONLY the rewritten question, no
preamble.
```

**Answer prompt**：

```
You are answering questions about a podcast show. Answer ONLY based on the
provided transcript chunks. Cite sources using [ep:<episode_id>@<start_time>]
after relevant claims. If the chunks don't contain the answer, say so. Reply
in the same language as the user's question.
```

**為什麼首輪跳過 rewrite**：首輪無 history，rewrite 等於抄一遍、花錢花時間無收益。

**Alternatives**：
- 全部輪次都 rewrite → 首輪浪費 1 次 LLM 呼叫
- 伺服端存 session → 未來擴充，非本 change 範圍

### Decision 7：Embedding 觸發點 — 轉錄 worker task 成功後同步呼叫

在 `workers/tasks.py::transcribe_episode` 成功寫入 `transcript_segments` 後：

```python
chunks = build_chunks(segments)
embeddings = openai_embed_batch([c.text for c in chunks])
save_chunks(db, transcript_id, chunks, embeddings)
```

這段在同一個 worker task 內完成（不開新 Celery task）。

**為什麼**：
- 轉錄與 embedding 綁定：使用者看到 `status=completed` 就代表可以查詢
- Embedding API call 快（幾秒內），worker 不會被拖住
- 失敗處理：embedding 失敗時把 transcript 標 `failed` 並寫 `error_message`，避免留下沒有 chunks 的「半完成」transcript

**Alternatives**：
- 另開 Celery task → 增加失敗狀態機複雜度，且無實際好處
- 定時 cron 補 embedding → 使用者體驗差（轉錄完但查不到）

## Risks / Trade-offs

- **Embedding 成本失控**：批次上限 64、worker 同步執行，大量 episode 集中 embed 時可能打到 rate limit。緩解：`openai_embed_batch` 內部 catch `RateLimitError` 並 exponential backoff（最多 3 次）
- **Zeabur AI Hub 未包含 embedding**：embedding 仍走 OpenAI 正式 endpoint。若未來要整合 AI Hub 的 embedding，需再檢視維度相容性
- **後台改 base_url / api_key 生效前舊查詢**：正在執行的 `/query` 不會中途切換（單次 request 讀一次 config 即鎖定），下一個 request 起生效。可接受
- **LLM 回答引用格式飄移**：prompt 要求 `[ep:<id>@<time>]` 但 LLM 不保證完全守格式。緩解：前端 parse 時用寬鬆 regex，parse 失敗就顯示純文字回答不帶引用；不重試
- **Multi-turn token 成本**：每輪 Answer LLM 會帶 history（最多 10 條訊息）+ 8 個 chunks 摘要，單輪約 5k tokens。gpt-4o 約 $0.025/輪、gpt-4o-mini 約 $0.0008/輪。可接受

## Migration Plan

1. Alembic migration：`ADD TABLE transcript_chunks`, `ADD TABLE llm_config`, `DROP COLUMN transcript_segments.embedding`
2. 既有 `transcript_segments` 的 `embedding` 欄位從未寫入資料，刪除無資料損失
3. 部署後既有 `transcripts` 的 chunks 尚未建立 — 新增一個 one-off script（或 API endpoint `POST /admin/reindex-all`）在驗證時用來對既有 transcripts 批次補 chunks + embeddings。此 script 不列入 applyRequires 的主流程任務，屬於部署輔助工具
4. 後台 LLM 設定首次使用時如 `llm_config` 為空，API 回 400 並提示先到後台填；或 seed migration 時插入一列空 key 的預設值，使用者填 key 後可用

## Open Questions

無（討論階段已收斂）。
