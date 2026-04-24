## Why

目前 `OpenAIWhisperProvider._split_audio` 用 `pydub.AudioSegment.from_file()` 把整個音檔 decode 成 uncompressed PCM 載入記憶體，導致 Zeabur worker 在轉錄 1 小時以上 podcast 時記憶體峰值飆到 1.5~2 GB，觸發 container OOM kill，進而產生 CrashLoopBackOff 並讓任務卡死在 Redis queue 中反覆重試。必須改為記憶體常數的音訊切段方式，才能在 Zeabur 現有 plan 上穩定運作。

## What Changes

- 重寫 `backend/app/services/transcription/openai_provider.py` 的 `_split_audio`：
  - 用 `ffprobe` 讀取音檔 duration（只讀 metadata，不 decode）
  - 用 `ffmpeg -ss <start> -t <duration> -i <input> -c copy <output>` 逐段 stream copy，**不 decode 也不 re-encode**
  - 移除對 `pydub.AudioSegment` 的依賴（此模組剩餘程式碼不再使用它）
- 切段後每個 chunk 的時長改為**近似等長**（對齊到最近的 MP3 frame / keyframe，誤差 ±1~2 秒），不再要求嚴格等長
- 維持現有對外行為：切段數仍為 `ceil(file_size_bytes / threshold_bytes)`；每段 offset 累加保持時間軸連續；失敗時 temp 目錄仍會被清理

## Non-Goals

- 不改變 `TranscriptionProvider` 介面或 `OpenAIWhisperProvider.transcribe` 的對外合約
- 不改變 `OPENAI_WHISPER_CHUNK_SIZE_MB` 預設值或設定機制
- 不處理 faster-whisper provider（本機推論記憶體問題與本 change 無關，屬獨立議題）
- 不實作 Celery 任務重試、並發控制或進度可見度（已列在 parked changes B2 / Change C）

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `transcription-pipeline`: 放寬「chunks of equal duration」為「approximately equal duration (aligned to nearest audio frame boundary)」，並更新實作說明由 pydub 改為 ffmpeg subprocess

## Impact

- Affected specs: `transcription-pipeline`（修改 Requirement: OpenAI provider handles oversized audio by chunking 的 scenario 與實作描述）
- Affected code:
  - Modified: backend/app/services/transcription/openai_provider.py
- Dependencies: 執行環境必須已安裝 `ffmpeg` 與 `ffprobe` CLI（目前 Dockerfile 已透過 apt 安裝 ffmpeg 套件，包含兩者）
- Runtime：worker container 記憶體峰值預期從 ~2 GB 降至 <200 MB；切段耗時從「decode + re-encode」降為近乎 bytes-copy，速度提升數倍
