## Context

兩個大集數節目（塞掐 444 集 / 台通 557 集，合計 1001 集、963 小時，2026-06-12 從 RSS 實抓）要加入 prod。現行轉錄管線：`cron_tick` 按 schedule 撈最新 N 集 → `enqueue_transcription` 建 pending queue row → dispatcher 派 Celery → `tasks._run` 呼叫 provider（prod 設定 = OpenAI whisper-1）→ post-ASR 持久化（同音字偵測、ASR 校正、segments、chunking、embedding dual-write）→ `_mark_queue_finished` 鏈式觸發 summary + topic。

全量走 whisper-1 約 $347 USD。已完成的評估（2026-06-12）：GCP spot GPU + faster-whisper large-v3-turbo 估 $5~10、品質同級；E407 十分鐘樣本實測 Groq 同模型輸出格式與中文品質皆可（`/tmp/groq_pilot/`）。GCP 帳號就緒（專案 `podcastrag`、billing enabled、us-central1 區域 L4/T4 配額各 1），唯 `GPUS_ALL_REGIONS` 0→1 申請處理中。

源碼查證錨點（propose 前已 grep）：
- 歷史集進 queue 的唯一自動路徑 = `cron_tick._enqueue_latest`（只對 enabled schedule、每 tick 最新 N 集、排除已有 completed/running/pending row）
- 建 show / sync 不建 schedule 也不 enqueue；`ShowSchedule` 只能由 admin schedules API 手動建立
- `tasks._run` 在 `provider.transcribe()` 之後的持久化段完全 provider-agnostic，只消費 `TranscriptionResult(text, language, segments)`
- 下游鏈式觸發位於 `_mark_queue_finished`（status=completed 時 enqueue summary + topic）

## Goals / Non-Goals

**Goals**
- 歷史集數轉錄成本從 $347 壓到 $20 以內（含下游 AI 步驟）
- 匯入路徑與現行 ASR 路徑共用同一條 post-ASR 持久化管線（行為零分歧）
- 全程不影響既有節目運作；兩新節目上線後新集數照現行 whisper-1 架構
- 批次過程可中斷續跑、可觀測、人工試水 gate 把關品質

**Non-Goals**
- 不做 Groq / 其他外部轉錄 provider 的常駐整合（曾評估 Groq free tier，因 developer tier 暫停升級 + 每日限額 8 audio-hr 出局；本 change 的外部轉錄是一次性工具不是 prod provider）
- 不動現行 whisper-1 provider、schedule、dispatcher 邏輯
- 不做 speaker diarization、不換 embedding 模型
- 不在本 change 內做兩新節目的 golden set / example prompts（後續 roadmap 處理）

## Decisions

### D1：重用縫 = 抽取 post-ASR 持久化共用函式

把 `tasks._run` 中 `provider.transcribe()` 回傳之後的持久化段抽成 `_persist_transcription_result(episode_id, result, *, queue_provenance)`（同檔案內部函式），ASR 路徑與匯入路徑都呼叫它。

- 替代案 A「匯入 endpoint 同步直寫」：否決——會複製貼上整段含同音字/校正/chunking/embedding 的邏輯，日後雙路徑漂移。
- 替代案 B「假 provider（讀檔案的 TranscriptionProvider）走完整 `_run`」：否決——`_run` 前半段含音檔下載/R2 上傳/25MB chunking，匯入不需要；硬塞會引入「假 audio path」的扭曲。
- 抽取為行為不變重構，比照 rag-py-module-split 的紀律：本地測試 baseline diff zero-new-failure。

### D2：歷史集隔離 = schedule 時序 SOP + 匯入寫 completed queue row（不加 schema）

- 上線順序固定：建 show + sync（無 schedule）→ 外部轉錄 → 匯入 → 驗收 → 最後建 schedule。期間 `cron_tick` 對該 show 完全不動作（無 enabled schedule）。
- 匯入 task 對每集建立／更新 queue row 為 `completed`、`whisper_model` 寫 `external:faster-whisper-large-v3-turbo`，使日後開 schedule 時 `_enqueue_latest` 的 NOT IN (completed|running|pending) 條件自然跳過。
- 替代案「episodes 加 `transcription_source` 欄位 / schedule 加 cutoff 日期」：否決——現有 queue row 機制已足夠表達，不加 migration。
- 殘餘風險：匯入期間若有人手動在 admin 對該集按「重新轉錄」會走 whisper-1 花錢——接受（admin 只有 Jacky，SOP 註明）。

### D3：匯入介面 = 單集 JSON endpoint + Celery task，idempotent

- `POST /admin/episodes/{episode_id}/transcript-import`（`require_admin`）。body = `{model: str, language: str|null, text: str, segments: [{start: float, end: float, text: str}]}`（與 whisper verbose_json 同構、欄位白名單）。一集約 0.3~0.8MB，1001 次呼叫可接受，不做批次壓縮上傳。
- 驗證規則：segments 非空、start/end 單調遞增且非負、text 非空；違反回 422。episode 不存在回 404；該集 queue row 為 pending/running（ASR 進行中）回 409 防互踩。
- endpoint 不同步寫 DB，只驗證 + enqueue `import_external_transcript` Celery task（走既有 `control` queue），回 202 + task id。重匯 = 覆寫（沿用 `_run` 既有 delete-then-write pattern），天然 idempotent。

### D4：GCP 跑器只負責轉錄，匯入從本機執行（prod 憑證不上 VM）

- VM：us-central1、g2-standard-4（L4）spot、Deep Learning image（CUDA 預裝）、50GB pd-balanced；faster-whisper large-v3-turbo、`condition_on_previous_text=False` + VAD filter（E407 實測防「字幕提供」幻覺循環）、`language=zh`。
- 跑器輸入 = 從 prod 匯出的集數清單（episode_id, audio_url, duration）；音檔由 VM 直接從 RSS enclosure 下載（ingress 免費）。逐集落盤 `out/{episode_id}.json` + `manifest.jsonl` 進度檔，可中斷續跑（重啟跳過已完成）；spot 被回收由 systemd 服務自動續跑。完成後 `gcloud storage cp` 回收結果並自動 `shutdown`。
- 匯入腳本在本機 Mac 跑（既有 E2E backdoor session SOP），逐集呼叫 D3 endpoint；併發 ≤ 2、集間 sleep，避免 embedding API / AI Hub 突刺（963 小時的 chunking+embedding 是真實負載）。
- 替代案「VM 直接打匯入 endpoint」：否決——admin session/CSRF 憑證要放上 spot VM，擴大攻擊面，且匯入節流邏輯放本機較好控。

### D5：分階段 gate

1. **配額 gate**：`GPUS_ALL_REGIONS` 核准後才開 VM；超過 48 小時未核准走 Console 手動申請。
2. **費用 gate**：先跑 1 小時樣本實測 RTF → 精算全量費用；預估超過 $30 USD 先回報確認（成本紀律線）。
3. **品質 gate**：先匯 5 集（兩節目都要有）→ Jacky 在 prod 抽看逐字稿頁/搜尋/deep-link → 拍板才全量匯入。
4. **下游成本 gate**：全量匯入前按 LLM 成本公式精算 embedding + summary + topic 費用並回報（估 $6~12）。

#### 試水品質標準（品質 gate 細則，2026-07-06 敲定）

兩層驗收：

1. **第一層 系統健康**（Claude 自動驗，全綠才給 Jacky 看）：5 集 transcript `status=completed`、`whisper_model=external:faster-whisper-large-v3-turbo`、每集有 chunks + embedding（非空）、summary 完成、topic 分段完成、queue 無 failed / 無卡住的 pending·running。
2. **第二層 人工抽看**（Jacky 拍板），顆粒度採「重點抽」：5 集逐字稿各快速掃一眼（確認無亂碼／大段漏字／語言辨識錯）；deep-link + 三模式只挑 2 集（含長集）深入試。

- **ASR 錯字容忍度**：「不影響理解就過」——少量人名／專詞誤字可接受，已知錯字走 T1 統一修，不擋這次上線。Blocker = 整段亂碼／大段漏字／跑出英文·簡體。
- **對話模式驗收三件事**：①答對、②有引用、③引用點進去對得上且語意正確（防「引用有掛卻答非所問」）。
- **選集原則**（候選池 → Jacky 挑最終 5 集）：兩節目各 ≥2 集；含 1 集 >60 分鐘長集（硬條件）；含 1 集短集；內容型態有差異（訪談 vs 閒聊）；至少 1 集需是 Jacky 聽過的集——三模式搜尋品質只有他能判斷答對沒。

### D6：匯入路徑跳過 LLM 同音字偵測（2026-07-07，試水後實測成本拍板）

全量匯入試水後,AI Hub usage 實測拆分打臉 task 4.4 的下游成本估算（$6~12）：
- **`asr_homophone` LLM 同音字偵測（gemini-3.5-flash）佔全量下游成本 73%**（實測 $0.204/集 中約 $0.15）；summary + topic（flash-lite）僅 27%。
- 根因：同音字偵測要 LLM 讀完整集找同音字誤植,gemini-3.5-flash 是 EQ2b `fe045a7` RAGEC pilot 拍板刻意選的貴模型；1001 集歷史批次逐集跑放大成本一個量級。
- 副作用：每集 `persist_candidates` 會灌入大量 pending 候選字,1001 集一次匯入產生海量待審,不適合批次匯入場景。

**決策**：`_persist_transcription_result` 加 keyword-only `skip_homophone: bool = False`；匯入路徑（`import_external_transcript`）傳 `True` 跳過整個 EQ2b 第一層（detect + persist_candidates），`llm_pairs=[]` 使第一層 `apply_corrections` no-op。**第二層 ASR 字典校正（EQ2a）不受影響照跑**。ASR 路徑維持 `False`,行為與抽取前完全一致（55 項 ASR/homophone 回歸測試驗證）。全量下游降到 ~$55。

- 破壞 D1「匯入與 ASR 路徑行為零分歧」原則——**限縮為「segments/chunks/embedding/summary/topic/字典校正零分歧,僅 LLM 同音字偵測在匯入路徑停用」**。對歷史批次可接受。
- 歷史集同音字修正改由 backlog「逐字稿轉錄品質系統性回掃 pipeline」（2026-07-06 提）統一批次處理——本來就規劃要做,且批次策略（抽樣 / 選高價值集 / 更省模型）比逐集 $0.15 更省。
- 替代案「換 flash-lite 重驗品質」：否決——需重跑 EQ2b pilot 對比,且只省 2.7x（全量仍 ~$110）,不如直接跳過 + 併入系統性回掃。

## Implementation Contract

- `_persist_transcription_result(episode_id: str, result: TranscriptionResult, *, queue_model_label: str) -> dict`：含 cancelled 檢查、segments/chunks delete-then-write、同音字偵測（fail-open）、ASR 校正、chunking、embedding dual-write、transcript content 重算、`_mark_queue_finished`（completed → 鏈 summary + topic）。ASR 路徑重構後行為不變（本地測試 baseline diff 驗證）。
- `import_external_transcript(episode_id: str, payload: dict) -> dict`（Celery，control queue）：payload → `TranscriptionResult` → 確保 queue row 存在（無則建 running，有 failed/cancelled 則 revive）→ 呼叫共用函式。
- 跑器 manifest 行格式：`{episode_id, status: done|failed, audio_seconds, elapsed_seconds, error|null}`；進度報告 = manifest 統計（done/failed/剩餘/預估完成時間）。
- 驗收（prod）：兩節目逐字稿頁可開、時間軸 deep-link 正確、語意/索引/對話三模式可查到新節目內容、queue UI 顯示外部模型標記、開 schedule 後 cron_tick 不重抓已匯入集（觀察一個 tick 週期）。
- `_persist_transcription_result(..., skip_homophone: bool = False)`（D6）：`True` 跳過 EQ2b LLM 同音字偵測（detect + persist_candidates），`llm_pairs=[]` 讓第一層 `apply_corrections` no-op；第二層字典校正照跑。匯入路徑傳 `True`,ASR 路徑維持 `False`。

## Risks / Trade-offs

- **spot 回收**：跑器 resumable + systemd 自動續跑；最壞情況改 on-demand（費用仍 < $20）。
- **大量匯入觸發 embedding/AI Hub 突刺**：本機匯入腳本節流（D4）；summary/topic 走既有 Celery queue 自然排隊，AI Hub 月預算 $60 需在下游成本 gate 確認餘裕。
- **外部轉錄品質差異**：large-v3-turbo vs whisper-1（large-v2）同家族、樣本已驗；ASR 校正字典 + 同音字管線照常生效；試水 gate 兜底。
- **匯入期間 prod 負載**：1001 集 chunking+embedding 分散數天分批，避開尖峰。
