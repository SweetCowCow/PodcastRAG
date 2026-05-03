## Context

PodcastRAG 已能完整轉錄 + 切 chunk + 向量化 + RAG 查詢。但「列集數」這層使用者看到的還是原始 RSS metadata：

- `episodes.title`：節目發佈時取的 title，多半可用但有時是「EP123」這種無資訊量。
- `episodes.description`：RSS feed 帶的描述，品質參差（廣告 / IG / 重點都有）。

依排路線圖 Phase A 與競品分析 A1，本變更要在不動轉錄流程的前提下，多一層 AI 寫的摘要（80-150 字繁中）覆蓋上去，並做到失敗對使用者透明（fallback 原描述）。

執行依賴：本變更**強制依賴 admin-llm-step-config**先 deploy 完成。Summary 用的 LLM endpoint / api_key / model 由那個變更建立的 `ai_steps.summary` row 提供，admin 在實際啟用前要把 `ai_steps.summary` 填好（base_url + api_key + model = `gpt-5-mini` via Zeabur AI Hub）。本變更 propose 階段可以開動，但 apply 階段（特別是端對端煙霧測試）必須等到 admin-llm-step-config 已 archive 並 deploy。

## Goals / Non-Goals

**Goals:**

- 新轉錄完成的集數，30 秒內自動有 AI 摘要可看（單集端到端 pipeline 應於 30 秒內完成）。
- 既有 657 集可由 admin 一鍵批次補上摘要（非自動，避免意外大額 LLM 費用）。
- 摘要失敗對使用者完全透明：UI 看到的就是原 RSS description，沒有「失敗」「請重試」字樣。
- 任何長度逐字稿（從 5 分鐘到 4 小時）都能產出可讀摘要，不因 context 上限報錯。
- Admin 看得到摘要狀態並可手動重跑單集 / 批次補。
- 所有 LLM 用量帳目在 admin-llm-step-config 的 `ai_steps.summary` 設定下集中記帳。

**Non-Goals:**

- 不做 ai_display_title。
- 不開放使用者重跑或請求重跑。
- 不做使用者編輯摘要 / 摘要評分。
- 不做多語摘要（只繁中）。
- 不在本變更實作 ai_steps.summary 的 admin 設定 UI（那是 admin-llm-step-config 的責任）。
- 不做摘要 cache 命中率 metric。
- 不做摘要與向量檢索的整合（是否把 ai_summary 也 embed 進向量空間留給 R2/R3）。

## Decisions

### D1: Map-reduce two-stage with 12K-token chunks

**Decision**：

- Stage 1（map）：用 `tiktoken` 的 `cl100k_base` encoding 計 token，對逐字稿純文字做 chunk 切分，每 chunk 上限 12,000 token，**chunk 邊界對齊 segment**（不切到一句中間）。每 chunk 的 prompt 大概是「請列出此段重點 3-5 條，純列點繁中，不必加標題」。
- Stage 2（reduce）：把所有 chunk 重點串接成單一字串，再丟一次 LLM 寫 80-150 字繁中流暢摘要。
- 兩階段都用 `ai_steps.summary` 同一組設定（同 model、同 endpoint）。

**Rationale**：

- 12K token 對 60 分鐘節目（~30K token）大約 3 個 chunk，2 小時節目（~60K token）大約 5 個 chunk，平均 LLM call 數可控（3-5 + 1 reduce ≈ 4-6 calls / 集）。
- Chunk 太大（24K+）會貴而且 LLM 的注意力對開頭與結尾偏好明顯，中段細節容易漏掉。Chunk 太小（<8K）會增加 reduce 階段重點數量，最後字數壓不住。
- 對齊 segment 邊界（不切句中）讓 chunk 重點寫起來連貫。

**Alternatives considered**：

- _單階段把整份逐字稿丟 LLM_：超長節目會超 context 上限或注意力被稀釋。
- _直接拿向量 chunks（已經切好，每 chunk 約 60s）做 map-reduce_：太碎（一集動輒 50-100 個 chunk），map 階段成本爆炸。
- _Stage 1 的 chunk prompt 要求字數限制_：實測 LLM 列點不限字數品質較佳，留給 reduce 階段壓字數。

### D2: ai_summary_status as 4-state enum, queue chaining via _mark_queue_finished

**Decision**：

- `ai_summary_status` enum：`pending` / `running` / `done` / `failed`。
- 預設 `pending`：episodes 表 INSERT 時就標 pending（migration 把既有 657 集也一併設為 pending，這樣「批次補摘要」不必特別過濾邏輯）。
- Celery task `generate_episode_summary` 進入後**先 UPDATE 為 `running`**（同一 transaction 鎖該行避免 race），結束時依結果 UPDATE 為 `done` 或 `failed`。
- Pipeline 鏈式 enqueue 點：`workers/tasks.py:_mark_queue_finished()` 在寫 transcription `status='completed'` 後 `generate_episode_summary.delay(episode_id)`。摘要 task 失敗**不**回寫 `transcription_queue` 任何欄位。

**Rationale**：

- 4-state 比 NULL + boolean / 3-state 都清楚；UI 可直接 switch 顯示。
- 預設 pending 而非 NULL 讓「批次補摘要」邏輯只需 `WHERE ai_summary_status='pending' AND transcript_status='completed'`，不必處理 NULL。
- `_mark_queue_finished` 是天然 hook 點，不增加新的觀察者 / event bus 機制。

**Alternatives considered**：

- _用 NULL 表示「沒摘要」，done/failed 為 status_：NULL 二義性（還沒跑 vs 失敗都看 NULL），UI 邏輯多分支。
- _Celery on_success / on_failure signal 來鏈式_：抽象多但對單一鏈式呼叫過度設計。
- _用 transcription_queue 的 finished_at signal 觸發 cron 而非鏈式 enqueue_：cron 延遲 1 min，使用者轉錄完還要等一分鐘才看到摘要，體驗差。

### D3: Failure transparent to end users, admin-only retry

**Decision**：

- 前端三個顯示點（PodcastSelect / QueryPage / TranscriptPage）的顯示邏輯：

  ```
  if ai_summary_status == 'done' and ai_summary:
      show ai_summary
  else:
      show episode.description (fallback)
  ```

  pending / running / failed 三狀態對使用者**長相完全一樣**（看到原 RSS description），不顯示 spinner、不顯示「摘要中」、不顯示「失敗」。

- Admin 端：QueueTab 列每集 row 顯示兩個 badge（transcript / summary）：
  - transcript badge 沿用既有設計
  - summary badge：`摘要中（pending+running 合併顯示）` / `已摘要（done）` / `失敗（failed）`。轉錄未完成的集數**不顯示** summary badge。
- 失敗 row 旁加 icon button「重跑」（POST `/admin/episodes/{id}/regenerate-summary`），把 status 改回 pending + enqueue。

**Rationale**：

- 失敗對使用者隱藏：使用者沒理由知道後端 LLM 故障，看到原 RSS description 已經是合理體驗。
- 不放 spinner：80-150 字摘要對使用者價值不到「一定要等」的程度；首集顯示原描述即可。Server push / WebSocket 的工程量遠超效益。
- pending + running 在 admin 合併成「摘要中」一個顯示：admin 不需要區分 task 是否已 worker pick 起來，看到「跑就是了」即可。

**Alternatives considered**：

- _前端顯示「AI 摘要產生中…」+ 30s 後 polling_：增加複雜度且 polling 浪費 round-trip。Fallback 顯示原描述更符合 progressive enhancement 原則。
- _前端顯示「摘要失敗，已通知管理員」_：對使用者來說是 noise；且當「失敗」是因 LLM provider 短暫 down，admin 重跑後就好，使用者不需要知道。

### D4: Backfill is admin-triggered, not automatic on migration

**Decision**：

- Migration 把既有 657 集的 `ai_summary_status` 設為 `pending`（預設值），但**不**自動 enqueue 657 個 task。
- 「批次補摘要」按鈕在 admin QueueTab 頂端，點擊 POST `/admin/episodes/backfill-summary`：後端 SELECT `ai_summary IS NULL AND transcript_status='completed'` 的集數，逐一 `generate_episode_summary.delay(episode_id)` enqueue，回傳 `{enqueued_count: N}` 讓前端 toast 顯示「已排入 N 集」。
- 沒有節流 / batch size 限制（657 集 × ~$0.001 = ~$0.7 一次補完，可承擔）。
- backfill 重複按下沒副作用：第二次按時，第一次已 enqueue 的 task 多半已開始（status=running），SELECT WHERE 會排除掉；如還沒開始（pending）會多 enqueue 一次但 task 進來會看到 row 仍 pending 然後正常跑，不會雙寫。

**Rationale**：

- 自動 enqueue 657 個 task 違反「成本警示」記憶規則 — 一上線就燒 $0.7 的 LLM quota，使用者該知情後再決定。
- 顯式按鈕 + toast 數量讓 admin 清楚當下發生什麼。
- 沒有節流是因為 throttle slot 機制（既有的 max_concurrent_transcriptions 那套）只管轉錄；摘要 task 不共用 slot，但 Celery worker concurrency=3 自然就限制了同時跑多少（會排隊在 broker），不會把 OpenAI rate limit 撞爆。

**Alternatives considered**：

- _migration 直接 enqueue 全部 657 個_：意外大開銷。
- _UI 拆成「補 10 集 / 50 集 / 全部」分批_：UX 過度設計，admin 看 toast 就知道進度。
- _enqueue 時加 batch_size=50 + 10s 間隔_：worker concurrency 已天然限制，不需要額外排程邏輯。

### D5: tiktoken on cl100k_base for chunking, segment-aligned boundaries

**Decision**：

- 用 `tiktoken.get_encoding('cl100k_base')`（GPT-4 / 4o family 通用 encoding）計 token。GPT-5 mini 可能會啟用 `o200k_base` — 屆時若有對齊問題再切（cl100k_base 估算值通常會偏高一點點，反而讓 chunk 更保守，是安全方向）。
- Chunk 切分演算法：accumulate `transcript_segments`（按 start_time asc），每次加一段時計目前 token 累計；當累計超過 12,000 token 時 close 當前 chunk，下一段開新 chunk。**最後一個 chunk 不論大小都保留**（不再 merge）。

**Rationale**：

- segment-aligned 讓每 chunk 結尾在自然句末，map prompt 的 LLM 不必處理半截句，重點品質較好。
- cl100k_base 是 OpenAI 公開最廣的 encoding，有 `tiktoken` 套件即支援；`o200k_base` 才出來不久，套件版本對應未必齊全。

**Alternatives considered**：

- _字元數估算（每中文字 ~1.5 token）_：誤差大，碰到包含英文 / 數字 / URL 的逐字稿會偏。
- _用 LLM provider 自己的 token endpoint（OpenAI `/v1/tokenize`）_：增加 round-trip，本地 tiktoken 完全等價。

### D6: Idempotency via short-circuit when status=done

**Decision**：

- `generate_episode_summary` task 進入後第一件事：SELECT episode `ai_summary_status`。
  - 若 `done` 且 `ai_summary` 不為空：log + return early（什麼都不做）。
  - 若 `running`：log warning（可能是上一個 task 還沒結束 / 或卡死），return early（不搶 row）。
  - 若 `pending` 或 `failed`：UPDATE 為 `running`，繼續跑。
- 「重跑」endpoint：`POST /admin/episodes/{id}/regenerate-summary` 的後端先 UPDATE `ai_summary_status='pending'`，再 enqueue task；這樣不會被 short-circuit 擋掉。

**Rationale**：

- 鏈式 enqueue + 批次補摘要 + admin 手動重跑三個入口都會呼到同一個 task，需要 idempotency 才安全。
- `running` 狀態 short-circuit 是防呆：避免兩個 worker 並行寫同一行。理論上有 transcription_queue + queue position 的 FIFO，加上 episode 一次只有一個 generate_summary task，碰撞極少；保留 short-circuit 是 belt-and-suspenders。

**Alternatives considered**：

- _用 SELECT FOR UPDATE 鎖行_：加複雜度，short-circuit 已夠。
- _不做 short-circuit，task 內每次都跑_：浪費 LLM 呼叫，特別是批次補摘要重複按下時。

## Risks / Trade-offs

- [⚠️ admin-llm-step-config 沒先 deploy] → 本變更程式碼會在第一次跑 task 時 raise `AiStepNotConfiguredError`（resolver 強制驗證），所有摘要 task 全失敗但**不影響轉錄**。Mitigation：tasks 寫明 admin 必須先在 admin-llm-step-config 上 deploy 完並設好 `ai_steps.summary` 才 deploy 本變更；release log entry 也要寫順序。
- [⚠️ 大量 backfill 撞 LLM rate limit] → 657 集連續 enqueue，按 worker concurrency=3 + 平均 4-6 calls / 集，瞬時可能達 ~30 calls/min，可能撞 rate limit。Mitigation：Celery autoretry on RateLimitError + exponential backoff。Rate limit 撞到不會炸，只會慢（task 自動 retry）。
- [⚠️ tiktoken 不在 dependency] → `pip install tiktoken` 是必要 task。Mitigation：tasks 1.X 列明 `pyproject.toml` / `requirements.txt` 要加。
- [⚠️ GPT-5 mini 還沒上線 / Hub 還沒支援] → 若實際部署時 Zeabur AI Hub 不支援 gpt-5-mini，admin 可在 ai_steps.summary 改用 gpt-4o-mini，本變更程式邏輯與 model 名稱解耦，不需要改 code。
- [⚠️ 摘要太短或太長（不在 80-150 字）] → 用 prompt engineering 控制（「請以 80-150 字繁體中文寫⋯」），但 LLM 不保證遵守。Mitigation：reduce 階段加 post-validation：若字數 < 50 or > 300，視為失敗並 retry 一次，再不行就接受實際長度（不阻擋 status=done）。極端值落在 5% 以下可接受。
- [⚠️ 失敗 fallback 顯示原 RSS description 是空字串] → 部分 RSS 沒帶 description（episodes.description IS NULL）。Mitigation：前端 UI fallback 鏈：`ai_summary` → `episode.description` → 空字串（不顯示該 section），不掉錯。
- [⚠️ Migration 把 657 集設 pending 卻不 enqueue —— admin 忘記點批次補] → 摘要永遠不會跑。Mitigation：admin queue tab 在 `pending count > 0 AND not enqueued recently` 時顯示 hint「有 N 集待生成摘要，點此批次補」。

## Migration Plan

1. **前置**：admin-llm-step-config 必須先 archive 並 deploy；admin 進入 ai_steps tab 把 `summary` step 設定填好（推薦 base_url=`https://hnd1.aihub.zeabur.ai/v1`、model=`gpt-5-mini`、api_key 指向 Zeabur AI Hub 的 key）。
2. 跑本變更的 alembic migration：episodes 表新增四欄，`ai_summary_status` 預設 `pending`，既有 657 集自動填 pending（不 enqueue）。
3. Deploy backend：新 task / 新 endpoint / 修改 `_mark_queue_finished` 鏈式 enqueue。
4. Deploy frontend：QueueTab 加 badge / 重跑 / 批次補；前台三處顯示 ai_summary fallback。
5. **驗證**：在 admin 對單一已轉錄集數點「重跑」，觀察 30 秒內 status `pending → running → done`，前台顯示新摘要。
6. **正式啟用**：admin 點「批次補摘要」開始補既有 657 集。預期 30-60 分鐘內全部完成（依 worker concurrency 與 rate limit）。
