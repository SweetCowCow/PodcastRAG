## 1. 環境與依賴確認

- [x] 1.1 確認 Dockerfile 透過 apt 安裝的 ffmpeg 套件包含 `ffprobe` 與 `ffmpeg` 兩個 CLI（在 worker container 內執行 `which ffprobe` 與 `which ffmpeg` 確認）
- [x] 1.2 移除 `backend/app/services/transcription/openai_provider.py` 頂部對 `pydub.AudioSegment` 的 import；若 backend 其他處無使用則從 `backend/requirements.txt`（或對應相依設定檔）移除 `pydub` 以減少 image 大小

## 2. 重寫 _split_audio（對應 Requirement: OpenAI provider handles oversized audio by chunking）

- [x] 2.1 在 `openai_provider.py` 新增私有函式 `_probe_duration_seconds(audio_path) -> float`，以 `subprocess.run` 呼叫 `ffprobe -v error -show_entries format=duration -of json <audio_path>`，解析 JSON 回傳 `format.duration` 的浮點秒數；對非零 return code 拋出 `RuntimeError` 並附帶 stderr 內容
- [x] 2.2 重寫 `_split_audio(audio_path, chunk_size_bytes, tempdir)`，實作 OpenAI provider handles oversized audio by chunking 的切段邏輯：用 `_probe_duration_seconds` 取得總秒數，用 `math.ceil(total_bytes / chunk_size_bytes)` 算出 chunk 數與每段時長
- [x] 2.3 在 `_split_audio` 的 chunk 迴圈中用 `subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{chunk_duration:.3f}", "-i", audio_path, "-c", "copy", chunk_path], check=True)` 切段，輸出 mp3 到 tempdir；對非零 return code 讓 `check=True` 自動拋出 `CalledProcessError`
- [x] 2.4 `_split_audio` 回傳 `[(chunk_path, start_offset_seconds), ...]`，其中 `start_offset_seconds` 為「請求給 ffmpeg 的 `-ss` 值」（而非實際 keyframe 對齊後的值），以維持既有 offset merging 行為

## 3. 保留既有對外行為（對應 scenarios: Chunk upload failure surfaces as exception / Temporary chunk files cleaned up）

- [x] 3.1 檢查 `_transcribe_sync` 的 `try/finally` 區塊不變：`shutil.rmtree(tempdir, ignore_errors=True)` 仍會在成功與例外路徑執行，確保 temp chunk 檔清理
- [x] 3.2 檢查上層 `_transcribe_sync` 仍會讓 chunk 上傳錯誤自然拋出（移除 pydub 後沒有新增的 try/except 吞掉 ffmpeg 或 API 例外）

## 4. 記憶體行為驗證（對應 Scenario: Splitting does not decode full waveform）

- [x] 4.1 在本機用一個 ≥ 60 分鐘的 podcast MP3（約 60MB+），跑一次 `_split_audio` 並用 `resource.getrusage(RUSAGE_SELF).ru_maxrss` 前後比較，確認 peak RSS 增加量 < 200 MB（若本機無 60+ 分鐘樣本，改用多次切 10MB 檔案以驗證記憶體不隨總時長線性增長）
- [ ] 4.2 在 Zeabur worker 上觸發一次真實轉錄任務，透過 `npx zeabur@latest service metric MEMORY --id 69eb1c620da29f05f49a4e2a` 觀察記憶體峰值 < 500 MB，且任務完成不再 OOM

## 5. 部署與回歸

- [ ] 5.1 push 到 GitHub 觸發 Zeabur 自動 build；透過 `npx zeabur@latest deployment log --service-id 69eb1c620da29f05f49a4e2a -t build` 確認 build 成功
- [ ] 5.2 部署後用一集歷史正常集數觸發轉錄，確認 `transcripts.status` 正常變為 `completed`、`transcript_segments` 數量與時間軸與舊實作相近（人工抽檢 3 組 `start`/`end` 與逐字稿對應音訊位置，誤差 ≤ 2 秒即通過）
- [ ] 5.3 確認 worker 在 idle 狀態無 CrashLoopBackOff，`Pod ... - BackOff` 錯誤不再出現於 runtime log
