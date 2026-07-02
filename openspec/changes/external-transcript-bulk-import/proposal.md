## Why

要新增「塞掐 Side Chat」（444 集）與「台灣通勤第一品牌」（557 集）兩個大集數節目，合計 963 小時歷史音檔。若照現行 whisper-1 流程全量轉錄需一次性支出約 $347 USD；改用 GCP spot GPU（faster-whisper large-v3-turbo）外部批次轉錄 + 匯入，轉錄成本可壓到估 $5~10，且品質同級（同為 Whisper large-v3 家族，2026-06-12 已用 E407 樣本實測格式相容、中文品質可接受）。

## What Changes

- **新增 admin 匯入 endpoint**：`POST /admin/episodes/{episode_id}/transcript-import`，接收外部轉錄結果（verbose_json 同構 payload：text / language / segments[].start/end/text），enqueue 匯入 Celery task。
- **新增匯入 Celery task**：從 payload 建 `TranscriptionResult` 後，重用既有 `_run` 的 post-ASR 持久化管線（同音字偵測、ASR 校正字典、segments、chunking、embedding dual-write、`_mark_queue_finished` 鏈式觸發 summary + topic）。**下游行為與現行轉錄路徑完全一致**。
- **重構抽取共用函式**：把 `backend/app/workers/tasks.py` 的 `_run` 中 `provider.transcribe()` 之後的持久化段抽成共用函式，ASR 路徑與匯入路徑共用（行為零改變）。
- **queue row 溯源標記**：匯入路徑建立／更新 `transcription_queue` row（completed + `whisper_model` 標記外部模型名），使 `cron_tick._enqueue_latest` 自然跳過已匯入集數，admin queue UI 正常顯示。
- **GCP 批次跑器工具**：`backend/scripts/gcp_batch_transcribe/` — VM 佈建指令、faster-whisper 批次轉錄（可中斷續跑、防幻覺參數、逐集落盤）、進度報告、結果上傳（呼叫匯入 endpoint）、跑完自動關機。
- **兩節目上線 SOP**（任務內執行，不改 code）：建 show + sync episodes（不建 schedule）→ GCP 全量轉錄 → 試水 5 集人工抽驗 gate → 全量匯入 → 確認 summary/topic 跑完 → 最後才建立 schedule（之後新集照現行 whisper-1 架構，零改動）。

## Capabilities

### New Capabilities

- `external-transcript-import`: 外部轉錄結果匯入——admin endpoint + Celery task + payload 驗證 + 溯源標記 + 與既有下游管線的重用契約。

### Modified Capabilities

- `transcription-pipeline`: post-ASR 持久化段抽取為共用函式（行為不變的架構不變式），並明訂兩條進入路徑（provider ASR / 外部匯入）共用同一下游。

## Impact

- Affected specs: `external-transcript-import`（新增）、`transcription-pipeline`（修改）
- Affected code:
  - New: backend/app/api/transcript_import.py、backend/app/workers/import_task.py、backend/scripts/gcp_batch_transcribe/（runner + 佈建文件）、backend/tests/test_transcript_import.py
  - Modified: backend/app/workers/tasks.py（抽共用函式）、backend/app/main.py（掛 router）
  - Removed: 無
