## Why

現有系統能夠透過 RSS 取得 Podcast 集數清單，但沒有任何方式產出逐字稿，使得後續 RAG 查詢完全無法啟動。為了推動 RAG pipeline 的核心功能（語意檢索、對話查詢），必須讓系統能夠把集數音檔轉為文字，並以句子為單位儲存時間戳記供檢索使用。

## What Changes

- 新增 Whisper 轉錄抽象層：定義 `TranscriptionProvider` 介面，同時實作 OpenAI Whisper API 與本機 faster-whisper 兩種 provider，以環境變數 `TRANSCRIPTION_PROVIDER` 決定採用哪一個。
- 新增音檔物件儲存層：透過 S3 相容的客戶端把 `episodes.audio_url` 對應的音檔落地到 Cloudflare R2，儲存 key 存於資料庫，供轉錄任務與後續 Whisper 使用；轉錄成功後不刪除音檔（支援重新轉錄）。
- 新增非同步任務隊列：以 Celery + Redis 作為任務隊列，新增 docker-compose 的 `redis` 與 `worker` 服務，提供 `transcribe_episode` 任務負責下載音檔 → 呼叫 provider → 寫入 `transcripts` 與 `transcript_segments`。
- 新增轉錄 API：
  - `POST /episodes/{episode_id}/transcribe`：建立/更新 `transcripts.status=pending` 並 enqueue 任務，回 `202 Accepted`；
  - `GET /episodes/{episode_id}/transcript`：回傳狀態與段落（status、error、segments[]）；
  - `POST /shows/{show_id}/transcribe-all`：批次 enqueue 指定節目尚未轉錄或上次失敗的集數。
- 資料庫擴充：在 `episodes` 表新增 `audio_storage_key`（nullable TEXT），用以記錄 R2 內的物件 key；`transcripts.status` 透過 `error_message`（nullable TEXT）記錄失敗原因。

## Non-Goals (optional)

（本變更 design.md 將建立，相關 Non-Goals 於設計文件的 Goals/Non-Goals 章節描述。）

## Capabilities

### New Capabilities

- `transcription-pipeline`: 將 episode 音檔轉成文字逐字稿的完整流程，涵蓋 Whisper provider 抽象、音檔下載/儲存、非同步任務隊列與 HTTP API。
- `object-storage`: 與 S3 相容（Cloudflare R2）物件儲存的抽象層，負責上傳、下載、取得 presigned URL。
- `task-queue`: Celery + Redis 組成的非同步任務基礎建設，供轉錄及未來重度工作（embedding、summary）共用。

### Modified Capabilities

- `db-schema`: 新增 `episodes.audio_storage_key` 欄位，以及 `transcripts.error_message` 欄位，以支援音檔落地與轉錄錯誤記錄。

## Impact

- Affected specs: `transcription-pipeline`（新）、`object-storage`（新）、`task-queue`（新）、`db-schema`（修改）
- Affected code:
  - `backend/requirements.txt`：新增 `celery[redis]`、`redis`、`boto3`、`openai`、`faster-whisper`、`pydub` 相依
  - `backend/docker-compose.yml`：新增 `redis` 與 `worker` 服務
  - `backend/app/core/config.py`：新增 Redis、R2、Whisper 相關設定
  - `backend/app/services/storage.py`：新增 R2 物件儲存 client
  - `backend/app/services/transcription/`：新增 provider 介面與 OpenAI / faster-whisper 實作
  - `backend/app/workers/`：新增 Celery app 與 `transcribe_episode` 任務
  - `backend/app/api/transcripts.py`：新增轉錄 API endpoints
  - `backend/alembic/versions/`：新增 migration 加上新欄位
