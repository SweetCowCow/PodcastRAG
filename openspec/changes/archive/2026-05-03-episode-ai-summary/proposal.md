## Why

PodcastRAG 目前列集數時只能顯示 RSS feed 帶來的 `title` + `description`。問題：

1. **節目原始描述品質參差**：股癌、台通等節目 RSS description 多半是行銷文案、廣告、來賓 IG，沒寫節目重點。使用者要決定「值不值得聽 / 是不是想找的那集」必須點進去看逐字稿。
2. **競品做了，我們沒做**：3 站競品分析（`docs/research/competitive-analysis.md`）裡，股癌站「聲音的形狀」唯一具差異化的 AI 元素就是每集 80-150 字 AI 摘要，而我們的優勢是多節目通吃，加上摘要是門檻低、效果立見的 ROI。
3. **RAG 體驗強化的前置**：之後 R2 / R3 改進的「跳到這段聽 + 段落上下文」要顯示集數背景，AI 摘要是最自然的展示位。

本變更為每集自動產出 80-150 字繁中摘要，存於 `episodes.ai_summary`，失敗對使用者完全隱藏（fallback 顯示原 RSS 描述），管理員可在 admin queue 頁看到摘要狀態並一鍵重跑。

## What Changes

- **DB schema**：`episodes` 表加四個欄位：`ai_summary` (TEXT, nullable)、`ai_summary_status` (enum: `pending` / `running` / `done` / `failed`，預設 `pending`)、`ai_summary_generated_at` (TIMESTAMP UTC, nullable)、`ai_summary_model` (VARCHAR(100), nullable，記錄當時用的 model 名以便事後追蹤)。
- **Celery task `generate_episode_summary(episode_id)`**：採 map-reduce 兩階段。
  - Stage 1（map）：把整份逐字稿（從 `transcripts` + `transcript_segments` 重組）依約 12,000 token 切 chunk，每 chunk 丟一次 `chat.completions.create()` 要 LLM 寫該段重點（純列點，不限字數）。
  - Stage 2（reduce）：把所有 chunk 重點串成一串，再丟一次 LLM 要 80-150 字繁中摘要。
  - 失敗：Celery `autoretry_for=(NetworkError, RateLimitError, ...)`、`retry_kwargs={'max_retries': 3, 'countdown': exponential}`。三次都失敗才寫 `ai_summary_status='failed'` + `ai_summary_generated_at=now`（記時間以便手動重跑判讀）。
  - LLM endpoint：透過 admin-llm-step-config 提供的 `services/ai_step_resolver.get_step_config('summary')` 取得 base_url + api_key + model。
- **Pipeline 鏈式 enqueue**：`backend/app/workers/tasks.py` 的 `_mark_queue_finished()` 在寫入 `status='completed'` 後 enqueue `generate_episode_summary.delay(episode_id)`。摘要任務的失敗**不**回寫 `transcription_queue.status`。
- **Token 計數**：使用 `tiktoken`（OpenAI tokenizer）做 chunk 切分，已是專案 dependency 的話直接用，否則 `pip install tiktoken`（後者寫在 tasks）。
- **Admin Queue Tab 強化**：
  - 每筆集數列除了現有 transcript badge 外，再加一個 summary badge（`摘要中` / `摘要完成` / `摘要失敗`）。轉錄未完成的集數不顯示 summary badge。
  - 摘要失敗 row 旁加「重跑」icon button：POST `/admin/episodes/{id}/regenerate-summary` 會把 `ai_summary_status` 設回 `pending` + enqueue task。
  - 整頁頂端加「批次補摘要」按鈕：POST `/admin/episodes/backfill-summary` 會把所有 `ai_summary IS NULL AND transcript_status='completed'` 的集數一次性 enqueue（回傳 enqueued 數量讓 UI toast 顯示）。
- **Episode list API**：`GET /shows/{show_id}/episodes` response 新增 `ai_summary` 與 `ai_summary_status` 兩欄（不暴露 `ai_summary_model` 給非 admin）。`GET /admin/episodes/...`（如有）新增四欄全部。
- **前端顯示**（三處）：
  - `PodcastSelect.jsx` 集數列表（如果該頁列集數）：每張集卡顯示 ai_summary（fallback `episode.description`）。
  - `QueryPage.jsx` 集數面板：同上。
  - `TranscriptPage.jsx` 頁面頂端：放在 episode title 下方獨立 section（fallback 原描述）。
  - 摘要狀態 `pending` / `running` / `failed` 一律 fallback 顯示原 RSS description，**不顯示 spinner / 失敗訊息**給使用者。
- **後台 backfill 機制**：本變更**不**自動 backfill 既有 657 集。Admin 必須手動點「批次補摘要」（避免一上線意外燒大筆 LLM quota，符合「成本警示」記憶規則的精神）。
- 雙語（zh / en）。

## Non-Goals

- **不做 `ai_display_title`**：先前討論決定，原 RSS title 多半 OK；硬改 title 會失去節目辨識度。
- **不做使用者主動重跑**：使用者前端看不到「摘要失敗」狀態，更不該有「請求重跑」按鈕。重跑只在 admin。
- **不做摘要編輯**：admin 不能手改摘要內容（避免衍生審核流程 / 內容權責問題）。要不滿就重跑。
- **不做多語摘要**：只產繁中摘要。要英文摘要的話留給未來變更。
- **不做摘要 cache 命中報告**：重複呼叫 `generate_episode_summary` 同一 episode_id 會直接 short-circuit（如果 `ai_summary_status='done'` 就略過），但不做 RAG 風格的 hit-ratio metric。
- **不在 PodcastSelect 第一層 / QueryPage 主面板加額外篩選器**（例如「只看有摘要的集」）。Phase A 不需要。

## Capabilities

### New Capabilities

- `episode-ai-summary`: 每集 AI 摘要的資料模型、產生 pipeline（map-reduce Celery task）、後台管理（summary badge / 失敗重跑 / 批次補摘要）、前端三處顯示與 fallback 行為。

### Modified Capabilities

(none. 既有 capability 對外契約延伸而非變更 — episode list 多兩欄、admin queue 多 summary badge / 重跑 / 批次補摘要、轉錄管線多一個鏈式 enqueue 點，這些行為都記錄在新 capability `episode-ai-summary` 的 spec 內。)

## Impact

- Affected specs:
  - 新增 `openspec/specs/episode-ai-summary/spec.md`
- Affected code:
  - New:
    - `backend/alembic/versions/<rev>_add_episode_ai_summary_columns.py`
    - `backend/app/workers/summary_task.py`（新 Celery task `generate_episode_summary`）
    - `backend/app/services/summary_pipeline.py`（map-reduce 邏輯：chunk 切分、map prompt、reduce prompt、token 計數）
    - `backend/app/api/admin/summary_ops.py`（regenerate / backfill 兩個 endpoint）
    - `backend/app/schemas/summary.py`（response models for backfill enqueue 結果）
  - Modified:
    - `backend/app/models/episode.py`（加四個欄位）
    - `backend/app/api/episodes.py`（list / detail response 加新欄位）
    - `backend/app/api/admin/__init__.py`（註冊 summary_ops router）
    - `backend/app/workers/tasks.py`（`_mark_queue_finished` 鏈式 enqueue）
    - `backend/app/workers/celery_app.py`（如要註冊新 task module）
    - `backend/app/schemas/episode.py`（response 加新欄位）
    - `src/AdminPage.jsx`（QueueTab 加 summary badge / 重跑 button / 批次補摘要 button）
    - `src/PodcastSelect.jsx`（集數列表顯示 ai_summary）
    - `src/QueryPage.jsx`（集數面板顯示 ai_summary）
    - `src/TranscriptPage.jsx`（頂端顯示 ai_summary）
    - `src/Shared.jsx`（如需共用 summary 顯示元件）
  - Removed: （無）
