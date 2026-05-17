## 1. 取證

- [x] 1.1 在 `backend/app/services/transcription/openai_provider.py` 的 `_transcribe_sync` 進場加 INFO log 印 `audio_path basename / os.path.exists / os.path.getsize / settings.openai_whisper_chunk_size_mb / chunk_size_bytes`，commit + push + deploy worker（落實 Requirement: Chunking decisions are observable in worker logs）
- [ ] 1.2 從 prod 抓一個 EP20-class（80 min 集）讓 worker 跑，撈 worker log 確認 `audio_path` 實際值跟 `getsize` 回應；判定 root cause（hypothesis：audio_path 是 R2 presigned URL 而非本地 temp 檔）

## 2. 修 root cause

- [ ] 2.1 依 1.2 結果修正：若 audio_path 是 URL → 在 `tasks.py` worker 進入 `_transcribe_sync` 前下載到本地 temp 檔再傳 path（落實 Requirement: Audio path resolution ensures local file before chunking）
- [x] 2.2 加 typed exception `RemoteAudioPathError` 到 `backend/app/services/exceptions.py`，`_transcribe_sync` 偵測到非本地 path 立刻 raise，worker 層 catch 並重新 download
- [x] 2.3 加 typed exception `OversizedAudioError` 同檔，並在 `_transcribe_sync` 上傳前 + 每個 chunk 上傳前都 size guard 25 MiB hard limit（落實 Requirement: OpenAI Whisper provider rejects oversized uploads with explicit error）

## 3. 測試

- [x] 3.1 寫 `backend/tests/test_openai_provider_chunking.py`：mock 26.4 MB tmp 檔，assert `_split_audio` 真的觸發、產 ≥2 chunks、每 chunk ≤ chunk_size_bytes
- [x] 3.2 同檔加 OversizedAudioError test：mock 26,214,401 bytes 檔 → assert raise + 無 HTTP call
- [x] 3.3 同檔加 RemoteAudioPathError test：mock audio_path=https://... → assert raise
- [x] 3.4 跑 `pytest backend/tests/` 全部，確認既有 transcribe 測試不退步

## 4. Prod 驗證 + 收尾

- [ ] 4.1 deploy worker 後手動 reset EP20 + 4-5 個 MaxRetries 集回 pending（在 admin Queue Tab 點重跑），驗證 80 min 集真的被 chunked + 完成 transcribe
- [ ] 4.2 撈 worker log 確認新 INFO 訊息 `decision=chunked chunks=N` 有出現
- [ ] 4.3 release log 補對應 entry：「修了長集（>22 MB）轉錄會悄悄失敗的 bug + 加上明確錯誤訊息」
