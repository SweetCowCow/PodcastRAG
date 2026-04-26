## Why

使用者目前無法在後台看到即時轉錄進度：每集的 pending / processing / completed / failed 狀態要展開每一集才看得到，失敗原因必須進 DB 查 `transcripts.error_message`。2026-04-24 的 OOM 修復 deploy 後首次觸發轉錄即因 OpenAI quota 用盡失敗，使用者需登入 OpenAI dashboard 才查得到原因，顯示後台對外部 API 的健康狀態可見度為零。本 change 同時補齊「每集進度彙總」與「外部 API 健康狀態」兩個可見度缺口，並修正 `transcripts.updated_at` 的 schema 補洞。

## What Changes

- 後端新增 `GET /shows/{id}/transcription-status`：回傳 `counts`（pending/processing/completed/failed）、`currently_processing`（執行中的 episode 列表）、`recent_failures`（最近 10 筆失敗，含 `error_category` 分類後的錯誤）
- 後端新增 `GET /admin/external-api-status`：回傳 OpenAI Whisper / Chat / Embedding 三個 API 的最近呼叫狀態（時間、成功與否、失敗則帶錯誤分類）
- 後端新增 `api_health` tracker service：用 Redis hash 記錄每個 API 最近 N=20 筆 call metadata（OpenAI provider、LLM answer/rewrite、embedding 呼叫點統一呼這個 tracker）
- 後端錯誤分類器：把 openai exception / HTTP status 轉成 `quota_exceeded` / `auth_error` / `rate_limited` / `server_error` / `network_error` / `unknown` 六類
- DB schema 補洞：`transcripts` 加 `updated_at` timestamptz 欄位（alembic migration，DB 層 trigger 或 SQLAlchemy `onupdate=func.now()` 自動更新）
- 前端 ScheduleTab：每張節目卡片可展開進度區塊（progress 數字 + currently_processing 區塊 + recent_failures 區塊），5 秒 polling
- 前端 AdminPage：新增「外部 API 狀態」tab，顯示三個 API 卡片（badge 顯示成功/錯誤分類），15 秒 polling
- 錯誤訊息顯示層面：前端將 `error_message` 截斷至 200 字並以 `error_category` badge 輔助說明

## Non-Goals

- 不做 token 額度用量計算或 cost estimation（需戳 OpenAI usage API，規模不值）
- 不做 SSE / WebSocket，固定 polling
- 不做 Prometheus / Grafana / 正式 APM 整合
- 不做獨立使用量統計 Dashboard（該工作另列技術債）
- 不在本 change 引入 Celery task retry 或 cross-pod 並發控制（B2 `concurrency-control-and-retry` 負責）
- 本 change 顯示的 queue 深度 / retry 計數欄位在 B2 尚未部署時以 `null` 呈現，前端相應隱藏，不等待 B2 完成即可獨立部署

## Capabilities

### New Capabilities

- `api-health-tracking`: 記錄外部 API 呼叫 metadata（時間、成功與否、錯誤分類）並提供查詢介面
- `transcription-progress-api`: 彙總單一節目所有集數的轉錄進度狀態查詢 endpoint
- `admin-external-api-status-ui`: 後台「外部 API 狀態」tab 的 UI 規範

### Modified Capabilities

- `transcription-pipeline`: OpenAI provider 在 transcribe 前後記錄 api-health tracker 事件，失敗時附錯誤分類
- `admin-show-management-ui`: ScheduleTab 的節目卡片改為可展開顯示進度區塊
- `db-schema`: `transcripts` 表新增 `updated_at` timestamptz 欄位，取代以 `transcribed_at` 作為「最後更新時間」的 workaround

## Impact

- Affected specs:
  - 新：`api-health-tracking`, `transcription-progress-api`, `admin-external-api-status-ui`
  - 改：`transcription-pipeline`, `admin-show-management-ui`, `db-schema`
- Affected code:
  - New:
    - backend/app/services/api_health.py
    - backend/app/schemas/api_health.py
    - backend/app/schemas/transcription_status.py
    - backend/alembic/versions/<timestamp>_add_transcripts_updated_at_and_api_health.py
    - src/ExternalApiStatusTab.jsx
  - Modified:
    - backend/app/api/shows.py
    - backend/app/api/admin.py
    - backend/app/services/transcription/openai_provider.py
    - backend/app/services/embedding.py
    - backend/app/services/llm_client.py（若存在；若不存在則在 answer/rewrite 實際呼叫點就地加 tracker）
    - backend/app/models/transcript.py
    - src/AdminPage.jsx
    - src/QueryPage.jsx（ScheduleTab 展開 UI；若 ScheduleTab 在獨立檔則改該檔）
    - src/Shared.jsx（需要新 Badge variant 或 ProgressBar 元件時）
  - Removed: (none)
- Dependencies:
  - Redis（已有）作為 api_health tracker 儲存後端
  - 不新增外部套件
- Runtime 風險:
  - 新增 polling：後端需承載前端每 5s / 15s 的輕量請求；`transcription-status` 為聚合 SQL，需確保有 index on `transcripts.status` + `transcripts.episode_id`；若效能不足再加快取
  - api_health tracker 寫入路徑位於 OpenAI 呼叫熱路徑，必須 fail-open（tracker 本身異常不能阻斷實際 API 呼叫）
