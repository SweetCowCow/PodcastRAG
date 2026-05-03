## 1. 前置確認

- [x] 1.1 確認 `admin-llm-step-config` 變更已 archive 並部署到 production；admin 已在 `ai_steps.summary` 設定 base_url + api_key + model（建議 `gpt-5-mini` via Zeabur AI Hub）。若未完成，apply 此 change 不該開工。
- [x] 1.2 在 backend dependency（`pyproject.toml` 或 `requirements.txt`）加入 `tiktoken`，重新 build / 安裝（對應 D5: tiktoken on cl100k_base for chunking, segment-aligned boundaries 的前置）。

## 2. DB schema

- [x] 2.1 撰寫 alembic migration：在 `backend/alembic/versions/<rev>_add_episode_ai_summary_columns.py` 為 `episodes` 表新增四欄（對應「Episodes table stores AI summary state」requirement）：`ai_summary` TEXT NULL、`ai_summary_status` ENUM('pending','running','done','failed') NOT NULL DEFAULT 'pending'、`ai_summary_generated_at` TIMESTAMPTZ NULL、`ai_summary_model` VARCHAR(100) NULL。Migration SHALL 把既有所有 row 的 `ai_summary_status` 設為 `pending`，且 SHALL NOT enqueue 任何 task。
- [x] 2.2 在 `backend/app/models/episode.py` 補上四個 column 對應的 `Mapped[...]` 欄位（含 enum python type）。
- [x] 2.3 在 `backend/app/schemas/episode.py` 把 `ai_summary` 與 `ai_summary_status` 加進 `EpisodeResponse`（一般 list/detail 皆暴露）；建立另一個 `AdminEpisodeResponse` 額外含 `ai_summary_generated_at` 與 `ai_summary_model`，僅 admin 路由使用。

## 3. Map-reduce summary pipeline

- [x] 3.1 建立 `backend/app/services/summary_pipeline.py`：核心函式 `run_summary(transcript_text_segments) -> str`，內含 chunk 切分（對應 D5: tiktoken on cl100k_base for chunking, segment-aligned boundaries —— 用 `tiktoken.get_encoding('cl100k_base')` 累計 token，每超過 12_000 close chunk，最後 chunk 不論大小保留）、stage 1 map prompt、stage 2 reduce prompt、字數 post-validation（< 50 或 > 300 重試一次後接受）。
- [x] 3.2 在 `summary_pipeline.py` 同一檔內定義 stage 1 prompt（要求列點 3-5 條繁中重點）與 stage 2 prompt（要求 80-150 字繁中流暢摘要）。注意 prompt 不放 episode title / description（只丟逐字稿原文，避免 LLM 抄）。
- [x] 3.3 寫單元測試（pure function）：給定假的 segments list（短 / 中 / 超長），驗證 chunk 切分結果（對應 D1: Map-reduce two-stage with 12K-token chunks 的 chunk count 表）、segment 邊界對齊（不切到 segment 中間）。

## 4. Celery task 與鏈式 enqueue

- [x] 4.1 建立 `backend/app/workers/summary_task.py`：定義 Celery task `generate_episode_summary(self, episode_id)`，bind=True，autoretry_for 含 NetworkError / RateLimitError / 5xx / Timeout，max_retries=3，countdown 採 exponential backoff（對應「Map-reduce summary task with retries」requirement）。
- [x] 4.2 在 task 進入點實作 D6: Idempotency via short-circuit when status=done：先 SELECT episode 的 `ai_summary_status`，若 `done` 且 `ai_summary` 非空 → log + return；若 `running` → log warning + return；若 `pending` 或 `failed` → UPDATE 為 `running` 後繼續。
- [x] 4.3 task 主流程：load transcript_segments、呼叫 `summary_pipeline.run_summary()`、用 `services/ai_step_resolver.get_step_config('summary')` 取得 LLM endpoint。pipeline 內每次 `chat.completions.create()` 都用 resolver 拿到的 base_url + api_key + model。
- [x] 4.4 Task 完成寫回：成功時 UPDATE `ai_summary=...`、`ai_summary_status='done'`、`ai_summary_generated_at=now()`、`ai_summary_model=<resolved model>`；失敗（3 retries 用盡）時 UPDATE `ai_summary_status='failed'`、`ai_summary_generated_at=now()`、`ai_summary` 保持 NULL。
- [x] 4.5 在 `backend/app/workers/celery_app.py`（如有）的 `imports` / `include` 加入 `app.workers.summary_task`，確保 worker 註冊到此 task。
- [x] 4.6 修改 `backend/app/workers/tasks.py` 的 `_mark_queue_finished()`：在寫 `transcription_queue.status='completed'` 之後（不在 `cancelled` / `failed` 分支裡）`generate_episode_summary.delay(episode_id)` 鏈式 enqueue（對應「Pipeline chains summary task after transcription completion」requirement，以及 D2: ai_summary_status as 4-state enum, queue chaining via _mark_queue_finished）。摘要 task 失敗不能回寫 transcription_queue。

## 5. Admin API endpoints

- [x] 5.1 建立 `backend/app/api/admin/summary_ops.py`：`POST /admin/episodes/{episode_id}/regenerate-summary` endpoint（對應「Admin endpoints for regenerate and backfill」requirement 的 regenerate scenario）：UPDATE row `ai_summary_status='pending'` + `delay()` task；404 if episode 不存在。
- [x] 5.2 在同一檔加 `POST /admin/episodes/backfill-summary`：SELECT `ai_summary IS NULL AND transcript_status='completed'` 的 episode，逐一 enqueue，回 `{enqueued_count: N}`。idempotent（可重複按）。
- [x] 5.3 在 `backend/app/api/admin/__init__.py` 註冊新 router（路徑 prefix `/admin/episodes`）。
- [x] 5.4 撰寫 pytest（含 admin auth fixture）：regenerate 200 / 404 / 403、backfill 計數正確、backfill idempotent（連按兩次第二次 count 約等於 0）。

## 6. Episode list API 改動

- [x] 6.1 修改 `backend/app/api/episodes.py` 的 `GET /shows/{show_id}/episodes`：response payload 加 `ai_summary` 與 `ai_summary_status`（對應「Episode list API includes ai_summary fields」requirement），SHALL NOT 包含 `ai_summary_model`（admin-only）。
- [x] 6.2 撰寫 pytest：在 fixture 中放三集分別為 `done` / `pending` / `failed` 三狀態，斷言 response 三集的 `ai_summary_status` 正確、且 response keys 不含 `ai_summary_model`。

## 7. 前端：使用者三處顯示

- [x] 7.1 在 `src/Shared.jsx` 加共用 helper `<EpisodeBlurb episode={ep} />`，邏輯依 D3: Failure transparent to end users, admin-only retry：若 `ep.ai_summary_status==='done' && ep.ai_summary` → render `ai_summary`；否則 render `ep.description || ''`（空字串時不渲染外層元素）。對應「User-facing display falls back to RSS description」requirement。
- [x] 7.2 在 `src/PodcastSelect.jsx` 集數列表卡片中插入 `<EpisodeBlurb>`（替換現有 `episode.description` 直接渲染處）。
- [x] 7.3 在 `src/QueryPage.jsx` 集數面板（右側可調整寬度的 panel）每筆 episode 處插入 `<EpisodeBlurb>`。
- [x] 7.4 在 `src/TranscriptPage.jsx` 頁面頂端 episode title 下方插入 `<EpisodeBlurb>`（獨立 section，可有自己的標題如「本集摘要」/「Episode summary」）。
- [x] 7.5 三處皆雙語（zh / en）；前台不顯示 spinner / 失敗訊息（D3 規定）。

## 8. 前端：Admin Queue Tab 強化

- [x] 8.1 在 `src/AdminPage.jsx` QueueTab 的每集 row 加 `<SummaryBadge ai_summary_status={...} />`（對應「Admin queue tab shows summary badge and controls」requirement）。badge 顯示規則依 D3: Failure transparent to end users, admin-only retry — `pending` 與 `running` 合併顯示 `摘要中` / `Summarising`；`done` 顯示 `已摘要` / `Summarised`；`failed` 顯示 `摘要失敗` / `Summary failed`。`transcript_status !== 'completed'` 不渲染 badge。
- [x] 8.2 失敗 row 旁加「重跑」icon button（既有 `<Btn icon="..." size="sm" variant="ghost">`），點擊 POST `/admin/episodes/{id}/regenerate-summary`，成功後 badge 應立即翻成 `摘要中`（refetch 或 optimistic update）。
- [x] 8.3 QueueTab 頂端加「批次補摘要」/ 「Backfill Summaries」button，點擊 POST `/admin/episodes/backfill-summary`；以 toast 顯示 `已排入 N 集` / `Queued N episodes`（依 D4: Backfill is admin-triggered, not automatic on migration）。
- [x] 8.4 在 QueueTab 頁頂顯示「待生成摘要 hint」：`pending count > 0 AND transcript_status='completed'` 時加一行小字「有 N 集待生成摘要，點此批次補」（對應 design 中針對 D4: Backfill is admin-triggered, not automatic on migration 提到的 Mitigation）。
- [x] 8.5 雙語所有 badge / button / toast / hint 文案。

## 9. 整合測試與部署驗證

- [x] 9.1 整合測試：在乾淨 DB 上跑 alembic migration，斷言 episodes 表多了四個欄位、所有 row `ai_summary_status='pending'`、無 task enqueue（對應「Episodes table stores AI summary state」的 migration scenario）。
- [x] 9.2 整合測試（mock LLM）：完整跑一遍 `_mark_queue_finished('completed') → generate_episode_summary` 鏈式流程，斷言 `ai_summary_status` 從 pending → running → done，row 結尾欄位皆正確。
- [x] 9.3 整合測試（mock LLM raises）：模擬 LLM 連續失敗 3 次，斷言 task 最終 retry 用盡並寫 `failed` + `ai_summary_generated_at`。`transcription_queue` 該 row SHALL 保持 `completed`（驗證「Pipeline chains summary task after transcription completion」failure scenario）。
- [x] 9.4 端到端煙霧測試（需 admin-llm-step-config 已 deploy）：在 admin 點某已轉錄集的「重跑」，30 秒內看到 `ai_summary_status='done'`，前台 PodcastSelect 顯示新摘要。

## 10. 文件與 release log

- [x] 10.1 更新 `docs/roadmap.md`：T3 從「Phase A 待做」搬到「已 archive 變更」區塊（archive 完才填）。
- [x] 10.2 更新記憶 `project_pending_changes.md`（依雙寫規則同步）。
- [x] 10.3 在 `src/releaseLog.jsx` 草擬 v0.7 entry（archive 後使用者再決定是否 commit）。
