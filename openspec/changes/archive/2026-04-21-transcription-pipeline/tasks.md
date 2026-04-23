## 1. 相依套件、設定與 docker-compose

- [x] 1.1 在 `backend/requirements.txt` 加入 `celery[redis]`、`redis`、`boto3`、`openai`、`faster-whisper`、`pydub`
- [x] 1.2 在 `backend/app/core/config.py` 新增 Celery、R2、Whisper 設定並更新 `.env.example`，涵蓋 R2 client configuration 所需的 `R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET / R2_ENDPOINT` 與 Celery application setup 所需的 `CELERY_BROKER_URL / CELERY_RESULT_BACKEND / TRANSCRIPTION_PROVIDER / OPENAI_API_KEY / FASTER_WHISPER_MODEL_SIZE / FASTER_WHISPER_COMPUTE_TYPE`
- [x] 1.3 在 `backend/docker-compose.yml` 新增 Redis service in docker-compose（含 `redis-cli ping` healthcheck）與 Worker service in docker-compose（重用 backend image、CMD 執行 `celery -A app.workers.celery_app worker --loglevel=info`，`depends_on` redis healthy + db healthy，掛 volume 快取 faster-whisper model）

## 2. 資料庫 schema 變更

- [x] 2.1 在 `backend/app/models/episode.py` 的 episodes table 加入 `audio_storage_key` nullable 欄位，並在 `backend/app/models/transcript.py` 的 transcripts table 加入 `error_message` nullable TEXT 欄位
- [x] 2.2 建立 Alembic migration for transcription columns：`alembic revision -m "add transcription columns"`，upgrade 新增兩欄位、downgrade 還原

## 3. Object storage service

- [x] 3.1 建立 `backend/app/services/storage.py` 封裝 boto3 S3 client 與 `StorageError` 例外，遵循「使用 S3 相容 client（boto3）操作 Cloudflare R2」設計，並在啟動時驗證 R2 相關環境變數
- [x] 3.2 實作 Upload audio from URL：以 `httpx` 下載至 temp、`put_object` 上傳，回傳 `storage_key`；HTTP 非 200 拋 `StorageError`
- [x] 3.3 實作 Download to temp file：`get_object` 寫入 `NamedTemporaryFile`，回傳路徑；物件不存在拋 `StorageError`
- [x] 3.4 實作 Presigned URL generation：呼叫 `generate_presigned_url('get_object', ..., ExpiresIn=expires_in)` 回傳 HTTPS URL

## 4. Task queue

- [x] 4.1 建立 `backend/app/workers/__init__.py` 與 `backend/app/workers/celery_app.py` 完成 Celery application setup，broker 與 result backend 取自 settings，開啟 `task_acks_late=True`、`worker_prefetch_multiplier=1`；實作決策「使用 Celery + Redis 作為任務隊列」
- [x] 4.2 建立 `backend/app/workers/dispatch.py` 的 Task dispatch helper `enqueue_transcription(episode_id)`，以 `celery_app.send_task("app.workers.tasks.transcribe_episode", args=[str(episode_id)])` 發送任務

## 5. Whisper provider 抽象

- [x] 5.1 建立 `backend/app/services/transcription/__init__.py`、`base.py`，定義 TranscriptionProvider abstraction 與 `TranscriptionResult`、`TranscriptionSegment` dataclass；對應決策「定義 TranscriptionProvider 抽象介面」
- [x] 5.2 建立 `backend/app/services/transcription/openai_provider.py`，以 `openai` SDK 呼叫 `audio.transcriptions.create(model="whisper-1", response_format="verbose_json")` 解析成 `TranscriptionResult`
- [x] 5.3 建立 `backend/app/services/transcription/faster_whisper_provider.py`，以 `WhisperModel(size, device, compute_type)` 執行 `transcribe(path, language=...)`，將 segments 映射到 dataclass，Model volume 使用 docker-compose 掛載
- [x] 5.4 建立 `backend/app/services/transcription/factory.py` 的 `get_provider()` factory，啟動階段驗證 `TRANSCRIPTION_PROVIDER` 為 `openai` 或 `faster-whisper`，否則拋錯

## 6. Worker 任務

- [x] 6.1 建立 `backend/app/workers/tasks.py` 實作 Transcribe episode worker task，照設計「Celery 任務 transcribe_episode 的步驟」依序：改 `processing`、必要時呼叫 `upload_from_url` 寫回「在 episodes 表新增 audio_storage_key 欄位」、`download_to_temp`、`provider.transcribe`、清空舊 segments、bulk insert 新 segments、改 `completed`；例外捕獲後寫「在 transcripts 表新增 error_message 欄位」並標 `failed`，`finally` 刪 temp 檔

## 7. API endpoints

- [x] 7.1 建立 `backend/app/api/transcripts.py` 實作 Transcribe episode endpoint（POST /episodes/{id}/transcribe 回 202 Accepted）：404 on missing episode、409 when status=`processing`、其餘 upsert `transcripts` 為 pending 並呼叫 `enqueue_transcription`；在 `backend/app/main.py` 掛載 router
- [x] 7.2 在同檔實作 Get transcript endpoint（GET /episodes/{id}/transcript），回 `status / language / transcribed_at / error_message / segments[]`，404 when 尚無 transcript
- [x] 7.3 在同檔實作 Batch transcribe endpoint（POST /shows/{show_id}/transcribe-all），篩選無 transcript 或 status=`failed` 的集數呼叫 `enqueue_transcription`，回 `{queued: N}`

## 8. 本地驗證

- [x] 8.1 `docker compose up -d --build` 啟動 db / redis / backend / worker，驗證四者 healthy，`docker compose logs worker` 看到 Celery 註冊 `transcribe_episode`
- [x] 8.2 端對端驗證：先 `TRANSCRIPTION_PROVIDER=openai` 對一集真實 episode 呼叫 `POST /episodes/{id}/transcribe`，輪詢 `GET /episodes/{id}/transcript` 直到 `completed`，檢查 `transcript_segments` 寫入；再把 `TRANSCRIPTION_PROVIDER` 切換成 `faster-whisper` 對另一集跑同樣流程
