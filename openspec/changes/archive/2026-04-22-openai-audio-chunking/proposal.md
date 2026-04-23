## Why

OpenAI Whisper API 對單次上傳有 25 MB 檔案大小上限；podcast 集數經常超過此限制（例如專案中第一次測試的 episode d9194bd8 是 26.3 MB 即被拒絕，回傳 HTTP 413）。目前 `OpenAIWhisperProvider` 遇到超過限制的音訊會直接讓 worker 捕捉例外並把 transcript 標記為 `failed`，使用者無法用 OpenAI provider 轉錄長集數，只能切換到 faster-whisper 或手動處理。為了讓 OpenAI 路徑能夠真正處理長音訊，provider 必須在轉錄前自動把大檔切片、分批呼叫 Whisper，最後合併逐字稿並調整每段 segment 的時間軸。

## What Changes

- 在 `OpenAIWhisperProvider` 內部加入「必要時自動分段」邏輯：當音訊檔案大於可設定的大小閾值（預設 24 MB，留 1 MB 給 multipart overhead）時，以 pydub 按時間切成連續 chunk、每段上傳至 Whisper API、再把結果合併成單一 `TranscriptionResult`
- 合併時：segment 的 `start` 與 `end` 加上該 chunk 在原檔中的起始秒數 offset；完整 `text` 為各段 text 依序串接並以空白分隔；`language` 取第一段回傳的語言
- 任何一段 chunk 呼叫 Whisper 失敗時，整個 `transcribe()` SHALL 拋出例外，使上層 worker 照現有流程把 transcript 標記為 `failed` 並紀錄錯誤訊息
- 切片產生的暫存 wav/mp3 檔案在合併後 SHALL 被清除（成功或失敗皆清）
- 新增設定項 `OPENAI_WHISPER_CHUNK_SIZE_MB`（預設 24）、`OPENAI_WHISPER_CHUNK_OVERLAP_SECONDS`（預設 0）允許調整切片大小與相鄰 chunk 之間的重疊秒數
- `faster-whisper` provider 不受影響（本機無 25 MB 限制）

## Non-Goals

- 不調整 `TranscriptionProvider` 介面簽名；切片與合併完全封裝在 `OpenAIWhisperProvider` 內部
- 不改動 worker task、API endpoint、資料庫 schema
- 不引入併行上傳（chunk 以順序方式呼叫 Whisper，避免 OpenAI 速率限制）
- 不處理相鄰 chunk 邊界重複語句的去重（採用 0 秒 overlap 預設，若使用者設為非零則單純重疊不去重）

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `transcription-pipeline`：`Requirement: TranscriptionProvider abstraction` 內 OpenAI provider 行為擴充，新增「音訊超過大小閾值時自動分段並合併」的 scenarios

## Impact

- Affected specs: `transcription-pipeline`
- Affected code:
  - `backend/app/services/transcription/openai_provider.py`
  - `backend/app/core/config.py`
  - `backend/.env.example`
  - `backend/requirements.txt`（pydub 已存在，如需 ffmpeg 支援須確認 base image）
