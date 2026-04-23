## Context

目前 backend 已能解析 RSS 並產出 `episodes` 清單，但 `transcripts` 表始終為空，整個 RAG pipeline 無法啟動。使用者希望能支援兩種 Whisper 來源（OpenAI API 與本機 faster-whisper）、透過 Celery + Redis 任務隊列執行非同步轉錄，並把音檔先落地到 Cloudflare R2 再送入 Whisper，讓重新轉錄不用再次下載。

限制條件：

- 既有 FastAPI 主程序仍以單一 container 執行；新增 worker 必須在同一份 image 中啟動不同 CMD。
- Docker Compose 目前只有 `db` 與 `backend`；新增 `redis`、`worker` 必須更新 healthcheck 與 `depends_on`。
- 既有資料庫已有 `transcripts` 與 `transcript_segments` 兩張表（由 backend-api change 建立），欄位結構不需大改，只需新增錯誤訊息欄位與 `episodes.audio_storage_key`。
- 開發者：使用者一人，本機使用 Docker Compose 開發，未來部署至雲端。

## Goals / Non-Goals

**Goals:**

- 提供可切換的 Whisper provider 介面（OpenAI / faster-whisper），使用者以環境變數決定。
- 提供完整的非同步轉錄流程：API 建立任務 → Celery worker 下載音檔 → 呼叫 provider → 儲存 transcripts/segments。
- 支援 R2 音檔儲存抽象，讓重新轉錄可直接從 R2 取得，而不必重新下載原始 audio_url。
- 提供查詢 API 讓前端能輪詢轉錄狀態與取得段落資料。
- `transcripts.status` 能正確反映 pending / processing / completed / failed 四種狀態，失敗時記錄錯誤訊息。

**Non-Goals:**

- 不在本 change 實作 embedding 產生或向量檢索（由後續 rag-query capability 處理）。
- 不實作轉錄結果的 LLM 後處理（摘要、分段、說話者分離）；Whisper 只回傳逐字稿與句級時間戳。
- 不處理轉錄費用統計與配額控管（未來 dashboard capability 處理）。
- 不在本 change 加入 WebSocket 推播，前端改以輪詢 `GET /episodes/{id}/transcript` 得知狀態。
- 不處理超長音檔（>4 小時）的自動分段，只在發現時回傳錯誤讓使用者後續處理。

## Decisions

### 使用 Celery + Redis 作為任務隊列

選擇 Celery 搭配 Redis broker，Celery 5.4.x 的官方發行版。Redis 亦作為 result backend。Worker 與 FastAPI 共用同一份 Docker image，但以不同的 CMD 啟動（`celery -A app.workers.celery_app worker`）。

考慮過的替代方案：

- RQ：語法更簡單，但缺少 Beat scheduler、retry 設定較單薄；Celery 對未來定期排程（週期同步、重試）支援較完整。
- FastAPI BackgroundTasks：只能跑在同一個 process，轉錄任務會阻塞 API 並佔用記憶體，不符非同步要求。

### 使用 S3 相容 client（boto3）操作 Cloudflare R2

使用 boto3 的 S3 client 搭配 R2 的 S3 相容 endpoint，以 `R2_ACCOUNT_ID`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY`、`R2_BUCKET`、`R2_ENDPOINT` 作為設定。新增 `AudioStorageService` 封裝 `upload_from_url(url) -> key`、`download_to_temp(key) -> path`、`get_presigned_url(key) -> str` 三個操作。

考慮過的替代方案：

- 直接使用 `cloudflare` 官方 SDK：R2 目前主推 S3 相容介面，官方 SDK 支援度較弱。
- MinIO client：需額外依賴；boto3 本身足夠且為 AWS S3、R2、B2 的共同抽象。

### 定義 TranscriptionProvider 抽象介面

建立 `TranscriptionProvider` 抽象類別，暴露 `async def transcribe(audio_path: str, language: str | None) -> TranscriptionResult`。`TranscriptionResult` dataclass 包含 `text: str` 與 `segments: list[TranscriptionSegment]`（start、end、text）。實作兩個子類：`OpenAIWhisperProvider`（以 `openai` SDK 呼叫 `audio.transcriptions.create`，指定 `response_format="verbose_json"` 以取得段落時間戳），以及 `FasterWhisperProvider`（以 `faster-whisper` package 在本機跑 `WhisperModel(model_size, device, compute_type).transcribe(...)`）。`get_provider()` factory 依 `settings.transcription_provider` 回傳對應 instance。

考慮過的替代方案：

- 直接在任務裡寫條件分支：會讓 worker 任務測試困難。
- 僅支援單一 provider：不符合使用者 ROI 要求（想看開發/上線成本差異）。

### 在 episodes 表新增 audio_storage_key 欄位

在 `episodes` 表加上 `audio_storage_key VARCHAR NULL`，轉錄任務開始時若尚未有 key，則下載 `audio_url` 上傳到 R2 並回填。重新轉錄時直接從 R2 取檔，不再連 audio_url。遇到 audio_url 與現有 key 皆取不到音檔時，任務標為 failed。

考慮過的替代方案：

- 另建 `audio_files` 表：過度設計；目前 episode 與音檔 1:1 對應。
- 不落地 R2，每次轉錄都重新下載：違背使用者「重新轉錄不重下載」需求。

### 在 transcripts 表新增 error_message 欄位

在 `transcripts` 表加上 `error_message TEXT NULL`。狀態流轉：建立時 `pending`，worker 取到後改 `processing`，成功後改 `completed` 並清空 error_message，失敗則 `failed` 並寫入錯誤訊息（截斷到 2000 字）。

考慮過的替代方案：

- 用另一張 `transcript_events` 表記錄錯誤：目前只需最後一次錯誤，過度設計。

### POST /episodes/{id}/transcribe 回 202 Accepted

該 endpoint 同步完成三件事：查 episode 是否存在（不存在回 404）、upsert `transcripts` row 狀態為 pending 並清空 error_message、以 Celery `send_task` enqueue `transcribe_episode(episode_id)`，接著立即回 `202 Accepted` 含 `{transcript_id, status, queued_at}`。若 episode 已有 `transcripts.status=processing`，回 `409 Conflict` 不重複排入。

考慮過的替代方案：

- 回 200：不符合非同步任務慣例，前端難以辨識。
- 等 worker 取走才回應：破壞非同步隔離。

### Celery 任務 transcribe_episode 的步驟

Worker 任務步驟：

1. 從 DB 取 episode 與 transcripts row（應存在），將 status 改為 processing。
2. 若 `audio_storage_key` 為空，呼叫 `AudioStorageService.upload_from_url(episode.audio_url)` 取得 key 並寫回 DB。
3. 呼叫 `AudioStorageService.download_to_temp(key)` 取得本地 temp 檔路徑。
4. 透過 `get_provider().transcribe(path, language=episode.show.language)` 取得結果。
5. 把 `result.text` 存入 `transcripts.content`、delete 舊的 `transcript_segments`、bulk insert 新段落。
6. 將 `transcripts.status` 改 `completed`，清空 `error_message`，`completed_at` 設為 utc now。
7. 任何例外捕獲後 status 改 `failed`、錯誤訊息寫入 `error_message`，並讓 Celery 視為失敗（不自動重試，避免持續扣 API 費用）。
8. `finally` 刪除 temp 檔。

## Risks / Trade-offs

- [轉錄耗時長導致任務堆積] → Worker concurrency 預設 2，使用者可在環境變數調整；使用 Celery 的 `task_acks_late=True` 確保 worker 掛掉時任務不丟失。
- [OpenAI API 費用不可控] → 首版不在後端加配額，但在 README 明列使用風險，使用者可切換至本機 faster-whisper 控制成本。
- [faster-whisper 在 CPU 上非常慢] → 讓使用者透過 `FASTER_WHISPER_MODEL_SIZE`（預設 `base`）、`FASTER_WHISPER_COMPUTE_TYPE`（預設 `int8`）調整，並在文件說明 GPU 環境建議。
- [R2 憑證外洩] → 僅在 `.env` 中設定且不納入版控；`.env.example` 提供樣板。
- [音檔下載失敗] → 只嘗試一次 audio_url；失敗即任務 failed。後續可在 dashboard 加 retry 按鈕。
- [episode.show.language 為 None 時 Whisper 自動偵測可能偵測錯誤] → 若為 None 則傳 `None` 給 provider 讓 Whisper 自動偵測；faster-whisper 與 OpenAI API 皆支援自動偵測。
- [Celery worker 與 FastAPI 共用 image 導致體積增大] → faster-whisper 會下載 model 檔案到容器；預設使用 volume 快取 model，避免每次啟動都重新下載。
