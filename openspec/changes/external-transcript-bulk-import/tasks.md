## 1. 共用持久化函式抽取（行為不變重構）

- [x] 1.1 跑本地測試基線：執行 backend 全測試套件並保存結果清單（基線檔落盤 /tmp 或 .tmp，後續 diff 用），確認重構前的 fail 清單
- [x] 1.2 從 backend/app/workers/tasks.py 的 `_run` 抽出 `_persist_transcription_result(episode_id, result, *, queue_model_label)`：涵蓋 cancelled 檢查、segments/chunks delete-then-write、`asr_homophone.detect_homophones`（fail-open）、`asr_correction.apply_corrections`、`build_chunks`、`embed_texts_dual`、transcript content 重算、`_mark_queue_finished`。`_run` 改為呼叫共用函式；`transcribe_episode` 對外行為與簽章不變
- [x] 1.3 重跑全測試套件與 1.1 基線 diff：zero-new-failure 才算過；驗收 = diff 報告貼進 task 紀錄

## 2. 匯入 Celery task + admin endpoint

- [x] 2.1 新增 backend/app/workers/import_task.py：Celery task `import_external_transcript(episode_id, payload)`（control queue）— payload → `TranscriptionResult`；確保 queue row 存在（無則建、failed/cancelled 則 revive），最終 completed 且 `whisper_model="external:faster-whisper-large-v3-turbo"`；呼叫 `_persist_transcription_result`；下游失敗時 transcript 標 failed 且不留 partial chunks
- [x] 2.2 新增 backend/app/api/transcript_import.py：`POST /admin/episodes/{episode_id}/transcript-import`（require_admin）— payload 白名單驗證（segments 非空、0<=start<=end、text 非空 → 違反 422）、episode 不存在 404、queue row pending/running 409、通過則 enqueue 回 202 `{task_id, episode_id}`；在 backend/app/main.py 掛 router
- [x] 2.3 新增 backend/tests/test_transcript_import.py：覆蓋 spec 全 scenario — 202 happy path、422 三種壞 payload、404、409、佇列 row 建立/revive 溯源標記、re-import 覆寫 idempotency、embedding 失敗 → transcript failed；mock provider/embedding 比照既有測試慣例

## 3. GCP 批次跑器工具

- [x] 3.1 新增 backend/scripts/gcp_batch_transcribe/：`provision.sh`（建 spot L4 VM us-central1 + Deep Learning image + 50GB disk 的 gcloud 指令與還原/刪除指令）、`runner.py`（faster-whisper large-v3-turbo、`condition_on_previous_text=False` + VAD filter、language=zh、逐集落盤 out/{episode_id}.json、manifest.jsonl 續跑、systemd unit 範本含 spot 回收自動續跑、全部完成自動 shutdown）、`export_episode_list.py`（從 prod 匯出 episode_id/audio_url/duration 清單）、`import_results.py`（本機節流匯入：併發<=2、集間 sleep、失敗清單重試）、README（操作 SOP）
- [x] 3.2 跑器本機冒煙：用 E407 十分鐘樣本在 Mac 以 CPU 模式跑 runner.py 驗 manifest/續跑/輸出 schema 與 2.2 endpoint payload 契約一致（不開 VM、零費用）

## 4. GCP 實跑（三道 gate）

- [x] 4.1 配額 gate：確認 `GPUS_ALL_REGIONS` 核准（`gcloud beta quotas preferences describe`）；超過 48 小時未核准改走 Console 手動申請並回報 Jacky
- [x] 4.2 費用 gate：開 VM 跑 1 小時樣本（兩節目各取一集的前 30 分鐘）實測 RTF 與品質 → 精算全量費用；估算 > $30 USD 先回報 Jacky 確認再續
- [x] 4.3 全量轉錄：兩節目 1001 集分批跑完；驗收 = manifest done 計數 = 集數、failed 清單處理完（重試或記錄豁免原因）、結果 JSON 全數回收到本機
- [x] 4.4 下游成本 gate：按 LLM 成本估算公式精算 embedding + summary + topic 全量費用與 AI Hub 月預算餘裕，回報 Jacky 確認後才開始匯入

## 5. 節目上線與試水

- [x] 5.1 兩節目建入 prod：admin 建 show（塞掐 Side Chat / 台灣通勤第一品牌，RSS 為 2026-06-12 評估時確認的 feed URL）+ sync episodes；驗收 = 集數與 RSS 一致、**不建 schedule**、queue 零 row
- [x] 5.2 試水匯入 5 集（兩節目都要有，含一集 >60 分鐘長集）→ 確認 summary/topic 鏈式跑完 → Jacky 在 prod 抽看逐字稿頁/時間軸 deep-link/三模式搜尋品質；**Jacky 拍板通過才繼續**

## 6. 全量匯入與驗證

- [ ] 6.0 【D6，2026-07-07 試水後插入】匯入路徑跳過 LLM 同音字偵測：試水匯入 162 集實測 AI Hub 燒 $31.96（$0.204/集,外推全量 ~$205,遠超 task 4.4 估的 $6~12）；usage 拆分定位大頭 = `asr_homophone`（gemini-3.5-flash）佔 73%。`_persist_transcription_result` 加 `skip_homophone`,匯入路徑傳 True；ASR 路徑不變（55 項回歸綠 + 新增 test_import_skips_homophone_detection）。部署 prod → 驗證新匯入集 AI Hub 消耗降到僅 summary+topic（~$0.055/集）。同音字修正併入 backlog 系統性回掃 pipeline
- [ ] 6.1 全量分批匯入（D6 後）：import_results.py / full_import_orchestrator.py 分批執行（每批後檢查 worker queue 積壓與 AI Hub 用量），匯入完成驗收 = 兩節目 transcript completed 數 = 集數、summary/topic 完成率 100%（或失敗清單處理完）；全量下游成本目標 ~$55
- [ ] 6.2 建立兩節目 schedule（enabled）：觀察一個 cron tick 週期，驗收 = `_enqueue_latest` 對已匯入集零 enqueue（queue 無新增 row）、新發布集數照常進 whisper-1 流程
- [ ] 6.3 Prod smoke：兩節目逐字稿頁、`?t=` deep-link、語意/索引/對話三模式各一查詢回有效結果、admin queue UI 顯示 `external:` 模型標記

## 7. 收尾

- [ ] 7.1 Spec sync 確認 + 文件：case study `docs/case-studies/external-transcript-bulk-import-2026-06.md`（評估歷程、實測 RTF、費用 actual vs 估計、時程 calibration 一行）；GCP VM 刪除 + 費用 actual 紀錄
- [ ] 7.2 Release log 草稿（兩新節目上線，使用者視角）給 Jacky review 後寫入
