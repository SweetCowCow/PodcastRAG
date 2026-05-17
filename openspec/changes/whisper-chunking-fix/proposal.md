## Why

2026-05-10 prod 觀察：worker `OPENAI_WHISPER_CHUNK_SIZE_MB=22` env 設定生效（`settings.openai_whisper_chunk_size_mb=22` 已驗）但 OpenAI Whisper API 仍收到 25+ MB 整檔上傳，10+ 次 HTTP 413 失敗。EP20（Axios，26.3 MB / 80 min 集）跟其他 4-5 集大檔卡住，每個 retry 占用 worker slot ~30s 且最終失敗。`openai_provider._transcribe_sync` 的 chunking 分支沒被走到，但 root cause 未確定（hypothesis：`audio_path` 在 chunking check 之前指向錯的東西，譬如 R2 URL 而非本地下載完的 temp 檔）。

## What Changes

- 在 `openai_provider._transcribe_sync` 進場加 debug log 印 `audio_path / os.path.exists(audio_path) / os.path.getsize(audio_path) / settings.openai_whisper_chunk_size_mb / chunk_size_bytes`，部署一次取證
- 依 debug log 結果修正 root cause（最可能：audio_path 指 R2 presigned URL 不是本地檔；fallback：getsize 對 URL 回 0；fix = 確保進入 `_transcribe_sync` 的 path 已是本地下載完的 temp 檔）
- 新增 unit test `test_openai_provider_chunking.py` 用 mock 的 26.4 MB tmp 檔驗證 `_split_audio` 真的觸發、產出至少 2 個 chunks、每個 chunk size <= chunk_size_bytes
- 新增 integration smoke：在 `transcribe_episode` 的 sync wrapper 加 explicit guard — 若 file > 25 MiB OpenAI 硬上限，refuse 上傳並 raise 明確 exception（防 silent 413 燒 retry）
- 部署後手動 reset EP20 + 4-5 個之前 MaxRetries 集回 pending 重轉

## Non-Goals

- 不重做 `_split_audio` ffmpeg 邏輯（保留 stream copy + keyframe 對齊行為）
- 不改 chunk_size_mb 預設值（保持 22 / env 可調）
- 不做 faster-whisper provider 的對應檢查（admin UI 已 disable，記憶 `feedback_pptx_*` 不相關）
- 不引入新的轉錄 provider（DeepGram / AssemblyAI 等屬未來 R5 範疇）
- 不做 progress streaming（chunked upload 完成才回，跟現況一致）
- 不更動 EP20 case study root cause 標記（EP20 卡 9hr 的 root cause 是 F1 queue routing，不是本 change）

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `transcription-pipeline`: chunking 邏輯加 explicit guard 防 silent 413；audio_path resolution 修正

## Impact

- Affected specs: `transcription-pipeline`
- Affected code:
  - Modified:
    - `backend/app/services/transcription/openai_provider.py`（debug log + audio_path resolution + 25 MiB hard guard）
    - `backend/app/workers/tasks.py`（如 audio_path 是在 worker 層解析，調整下載順序）
  - New:
    - `backend/tests/test_openai_provider_chunking.py`
