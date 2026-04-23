## 1. 設定與相依套件

- [x] 1.1 落實 Decision 4：閾值預設 24 MB，留 1 MB 給 multipart overhead——在 `backend/app/core/config.py` 的 `Settings` 新增 `openai_whisper_chunk_size_mb: int = 24`、`openai_whisper_chunk_overlap_seconds: int = 0`（對應環境變數 `OPENAI_WHISPER_CHUNK_SIZE_MB`、`OPENAI_WHISPER_CHUNK_OVERLAP_SECONDS`），並在 `backend/.env.example` 補上兩個變數與說明
- [x] 1.2 檢查 `backend/Dockerfile` 是否已安裝 ffmpeg；若未安裝，加入 `RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*`，確保 pydub 能解碼 mp3/m4a

## 2. OpenAIWhisperProvider 分段邏輯（Requirement: OpenAI provider handles oversized audio by chunking）

- [x] 2.1 實作 Requirement: OpenAI provider handles oversized audio by chunking 的入口判斷：在 `backend/app/services/transcription/openai_provider.py` 新增常數 `_BYTES_PER_MB = 1024 * 1024` 並以 `os.path.getsize(audio_path)` 比對 `settings.openai_whisper_chunk_size_mb * _BYTES_PER_MB` 判斷是否觸發分段；不超過閾值時維持現有單次上傳路徑不動（對應 `Scenario: Small audio uses single request`）
- [x] 2.2 實作 Decision 1：以 pydub 按時間切片，閾值用檔案大小判斷——新增 `_split_audio(audio_path, chunk_size_bytes) -> list[tuple[str, float]]` helper，載入 `AudioSegment.from_file(audio_path)`，計算 `chunk_count = ceil(total_bytes / chunk_size_bytes)`、`chunk_ms = ceil(duration_ms / chunk_count)`，切出每段後 `export` 成 `tempfile.mkdtemp()` 目錄下的 mp3 檔，回傳 `[(chunk_path, start_offset_seconds), ...]`
- [x] 2.3 在 `_transcribe_sync` 分段分支中，對 `_split_audio` 回傳的每個 chunk 依序呼叫現有的 `audio.transcriptions.create(file=f, model="whisper-1", response_format="verbose_json", language=lang)`，取得各自的 segments 與 text
- [x] 2.4 實作 Decision 2：合併 segments 時把每個 chunk 的起始秒數加到 `start`/`end`——對每個 chunk 的 `TranscriptionSegment`，`merged.start = seg.start + offset`、`merged.end = seg.end + offset`；合併 `text` 以單一空格串接各 chunk 的 text；`language` 取第一個非 None 值；回傳合併後的 `TranscriptionResult`（對應 `Scenario: Oversized audio split and merged`）
- [x] 2.5 實作 Decision 3：暫存 chunk 存於 `tempfile.mkdtemp()` 目錄，finally 統一清理——在 `_transcribe_sync` 的分段分支用 `try/finally` 包住 chunk 產生與轉錄流程，`finally` 呼叫 `shutil.rmtree(tempdir, ignore_errors=True)`；任一 chunk 呼叫拋錯時讓例外傳出去，不回傳部分結果（對應 `Scenario: Chunk upload failure surfaces as exception` 與 `Scenario: Temporary chunk files cleaned up`）

## 3. 本地驗證

- [x] 3.1 `docker compose build backend worker && docker compose up -d` 重建含 ffmpeg 的 image；`docker compose exec backend python -c "from pydub import AudioSegment"` 確認 pydub 可載入無誤
- [x] 3.2 對先前失敗的 26.3 MB episode d9194bd8 以 `TRANSCRIPTION_PROVIDER=openai` 呼叫 `POST /episodes/d9194bd8.../transcribe`，輪詢 `GET /episodes/d9194bd8.../transcript` 直到 `completed`；檢查 `transcript_segments` 時間軸遞增、最後一段 `end_time` 接近 episode 的 `duration_seconds`
- [x] 3.3 對既有小於 25 MB 的 episode b89a4af2 重新轉錄一次，確認走單次上傳路徑（logs 只有 1 次 HTTP POST 到 `audio/transcriptions`）且 segments 結果與先前一致
