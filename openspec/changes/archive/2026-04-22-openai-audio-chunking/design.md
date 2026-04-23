## Context

`OpenAIWhisperProvider._transcribe_sync` 目前把整個音訊檔案以 `open(path, "rb")` 直接送給 `client.audio.transcriptions.create`，OpenAI 端會在檔案大於 25 MB 時回 413。專案中一集 26.3 MB 的 episode 已觸發此失敗。`faster-whisper` 為本機執行，不受此限制。

pydub 已於 `transcription-pipeline` 階段加入 `requirements.txt` 但尚未被使用；backend image 繼承 `python:3.12-slim`，需要確認 ffmpeg 已安裝（pydub 需要 `ffmpeg` 或 `libav` 才能解碼 mp3）。

## Goals

- OpenAI provider 在音訊超過閾值時能自動切片、批次上傳、合併結果為單一 `TranscriptionResult`
- 合併後的 `segments` 時間軸連續、對應到原始音訊
- 切片流程的 I/O（暫存檔）可靠清理，不造成磁碟洩漏
- 小於閾值的音訊走原本單次上傳路徑（零效能成本）

## Non-Goals

- 不改變 provider 介面或 worker 流程
- 不處理邊界語句重複（使用 0 秒 overlap 預設，overlap>0 時不做去重合併）
- 不做 chunk 併行上傳

## Decisions

### Decision 1：以 pydub 按時間切片，閾值用檔案大小判斷

以音訊檔案在磁碟上的 bytes 為切片觸發條件（`os.path.getsize(path) > chunk_size_mb * 1024 * 1024`）。切片時先用 `pydub.AudioSegment.from_file` 載入，用 `duration_ms // chunk_count` 計算每段長度（`chunk_count = ceil(total_bytes / threshold_bytes)`），export 成 mp3 暫存檔。

**為什麼**：檔案大小是 OpenAI 限制的直接指標；pydub 能處理 podcast 常見的 mp3/m4a。用時間平分而非位元組平分可避免切出無法解碼的半段。

**Alternatives**：
- 用 `ffmpeg` CLI 直接 `-ss / -t` 切片：避開 pydub 全檔載入的記憶體開銷，但需額外管理 subprocess 錯誤；pydub 已經是 requirements 成員，先走簡單路徑，若日後記憶體成為瓶頸再重構
- 由 Whisper API 自己處理：不支援，25 MB 為硬上限

### Decision 2：合併 segments 時把每個 chunk 的起始秒數加到 `start`/`end`

對 chunk `i` 產生的每個 segment，`merged.start = seg.start + offset_i`、`merged.end = seg.end + offset_i`，其中 `offset_i = sum(chunk_durations[:i])`。各 chunk 的 `text` 依序串接並以空白分隔成完整 `text`；`language` 取第一個非 None 的回傳。

**為什麼**：Whisper 對每段 chunk 的 `start`/`end` 相對於該 chunk 起點，需要加上 offset 才能映射回原始時間軸，供前端逐字稿頁面正確高亮。

**Alternatives**：
- 把 overlap 區的重複 segment 去掉：本提案採 0 秒 overlap 預設，使用者自訂非零 overlap 時簡單疊加不去重（避免文字比對啟發式造成錯誤）。後續若需精確去重可另提 change

### Decision 3：暫存 chunk 存於 `tempfile.mkdtemp()` 目錄，finally 統一清理

所有 chunk 檔案輸出到一個單一 tempdir，`_transcribe_sync` 以 `try/finally` 呼叫 `shutil.rmtree(tempdir, ignore_errors=True)`。

**為什麼**：即使某個 chunk 上傳失敗也要確保前面的暫存檔不殘留；tempdir 可一次性刪除，比逐檔 unlink 更穩。

### Decision 4：閾值預設 24 MB，留 1 MB 給 multipart overhead

`OPENAI_WHISPER_CHUNK_SIZE_MB` 預設 24。OpenAI 的 25 MB 上限是指 multipart/form-data 編碼後的總大小，audio bytes 之外還有 boundary、headers；留 1 MB 餘裕避免 edge case 413。

## Risks / Trade-offs

- [pydub 載入整個音訊到記憶體] → 單集 1 小時 mp3 解碼後 PCM 可達數百 MB，worker 記憶體需足夠。docker-compose 未設 `mem_limit`，現階段接受；若實測 OOM 再換 ffmpeg CLI 切片
- [合併時間軸偏移累積誤差] → 切片用 `AudioSegment[i*chunk_ms:(i+1)*chunk_ms]`，pydub 以 ms 精度切，累積誤差最多每段 ±1ms，對使用者不可感知
- [ffmpeg 未安裝] → pydub 解碼 mp3 依賴 ffmpeg；Dockerfile 若缺 `apt-get install ffmpeg`，切片會 raise `CouldntDecodeError`。實作時需驗證 image 已含 ffmpeg，若否則在 Dockerfile 加入
- [OpenAI 速率限制] → chunk 順序上傳避免觸發 RPM 限制；若單集需要大量 chunk（>10 段），總時間變長但不致失敗

## Migration Plan

1. 在開發環境對一集 >25 MB 的 episode 跑 `TRANSCRIPTION_PROVIDER=openai`，確認成功與 segments 時間軸正確
2. 如 ffmpeg 未安裝，在 Dockerfile 加 `RUN apt-get update && apt-get install -y ffmpeg`
3. 無資料庫或 API 變更，無回滾負擔；若 chunking 有問題，revert commit 即可

## Open Questions

無。
