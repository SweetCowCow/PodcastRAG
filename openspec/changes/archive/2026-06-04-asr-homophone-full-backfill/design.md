## Context

ASR 同音字校正系統現況（EQ2a–EQ2d 已上線）：

- **偵測層**（`asr_homophone.py`）：`detect_homophones`（RAGEC，對一份逐字稿叫一次 LLM 找候選）+ `persist_candidates`（寫 pending 候選，自帶 per-show dedup）+ `estimate_detection_cost`（不叫 LLM 的成本估）。三者皆已測試。目前只在轉錄 hook（新集）與 `scripts/homophone_pilot.py`（手動列 id）跑。
- **套用層**（`asr_correction.py` 的 `backfill_corrections` + `workers/tasks.py` 的 `backfill_asr_corrections`）：把已 approve 規則字面套到既有逐字稿，resumable per-transcript commit、per-chunk fail isolation；目前是純背景 Celery（無 `bind=True`），只回 `task_id`。
- **還原層**（EQ2d）：`segment.original_text` + `transcript.original_content` snapshot-once + per-episode `restore_episode`。

全站規模：3 節目、565 集、約 1,290 萬字。偵測一集一次 text LLM call，全站重跑估約 $2–4，但 565 次序列呼叫是數十分鐘的長作業。

## Goals / Non-Goals

**Goals:**

- F6：per-show 一鍵對既有集跑偵測、產 pending 候選，偵測不改逐字稿文字；先 dry-run 估成本 + 人工確認。
- F8：偵測與套用兩種長作業可查進度 / 可取消 / 失敗 chunk 可讀；批次 restore 一鍵還原一次套用涉及的集。
- F-approve：approve 候選時可選「順便套用既有集」，一個動作完成規則生效 + 舊集回套。

**Non-Goals:**

- 後台結構性重構（另開 discuss）。
- 偵測浮水印 / 增量。
- 偵測階段套用或改文字（一律須經人工 approve）。
- 取消即整批 rollback。

## Decisions

**D1 — F6 走獨立 service driver + 獨立 Celery task，不碰 `transcription_queue`。** 偵測是 text-only LLM，與轉錄（audio、貴、慢、priority=9 queue）差一個量級；塞進轉錄 queue 會搶資源且 overkill。新增 `services/asr_detection_backfill.py` 當批次驅動器：iterate 一節目既有集 → 對每集 `detect_homophones` + `persist_candidates` → 回報進度。對應新 task 走預設 `control` queue。

**D2 — 觀測用 Celery 原生 `update_state(state='PROGRESS', meta=...)` + `AsyncResult`，不自建進度表。** Redis result backend 已在用。兩種 task 都改 `bind=True`，每處理完一個單位（偵測=一集 / 套用=一份逐字稿）就 `update_state` 寫 `current` / `total` / `phase` / 累計 `failed_chunk_ids`。取捨見 Risks（不跨 result 過期存活）。

**D3 — 狀態查詢 endpoint 必須「整理」而非「轉發」。** `GET backfill-status/{task_id}` 把 `AsyncResult` 的 `state` + PROGRESS `meta` + 終態 return dict 統一成固定 response：`{ state, current, total, phase, failed_chunk_ids, message }`。PENDING / PROGRESS / SUCCESS / FAILURE / REVOKED 五態都映射到這個形狀，`message` 給人類可讀字串。禁止直接回 `AsyncResult.state`（seam 太薄）。

**D4 — 取消用 `AsyncResult.revoke(terminate=True, signal='SIGTERM')`。** 取消 = 停止繼續跑；已 commit 的 per-集 / per-逐字稿不回滾。狀態映射為 `REVOKED`，`message` 呈現「已取消，已處理 X/N」。

**D5 — F-approve：approve 帶 `apply_to_existing: bool`（預設 false）。** 為 true 時 approve 成功後 enqueue 一個帶該 `term_id` 的套用 task，response 多回 `task_id`；為 false 維持現行（只設 enabled）。沿用既有 `backfill_corrections(term_id=...)` 單規則路徑，不新增套用邏輯。

**D6 — F6 不蓋浮水印。** 重跑靠 dry-run 估 + 人工確認控成本；`persist_candidates` 既有 dedup 保證重跑不產生重複候選。

**[待決 D-A] 偵測並發度。** 序列跑 565 集（~數十分鐘）vs `asyncio` 小並發（限 5，縮到數分鐘）。並發會壓上 AI Hub rate limit 與 DB session 競爭，需在 apply 時量測再定；預設先序列、留並發為後續優化。

**[待決 D-B] 批次 restore 的範圍解析。** 兩個選項：(a) 精準追蹤——套用 task 記錄它改過的 episode id 集合，批次 restore 只還原這些；(b) 概略——還原所有「有 snapshot（`original_content IS NOT NULL`）的集」。(a) 精準但要落盤 task→episodes 對映；(b) 簡單但可能誤還原別次作業改的集。apply 時依是否已有 task 紀錄表決定。

## Implementation Contract

**Behavior（操作者觀察到的）：**

- 後台 ASR tab：選一個節目按「偵測既有集」→ 先看 dry-run 成本（集數 / 估 token / 估 USD）→ 確認後背景跑，畫面顯示 `current/total` 進度條，完成後新 pending 候選出現在審核區。
- 任何偵測 / 套用背景作業：可看即時進度、失敗 chunk 清單、可按「取消」。
- approve 候選時可勾「同時套用到既有集」；勾了就觸發一個可觀測的套用作業。
- 批次 restore：一鍵把一次套用作業改過的集還原回原始 ASR 文字。

**Interface / data shape：**

- `POST /admin/asr-corrections/detect-existing`：body `{ show_id: uuid, dry_run: bool=true }`。`dry_run=true` 回 `{ dry_run:true, episode_count, estimated_input_tokens, estimated_cost_usd, missing_transcript_ids }`；`dry_run=false` 回 `{ dry_run:false, task_id }`。
- `GET /admin/asr-corrections/backfill-status/{task_id}`：回 `{ state, current, total, phase, failed_chunk_ids, message }`（涵蓋偵測與套用兩種 task）。
- `POST /admin/asr-corrections/backfill-cancel/{task_id}`：回 `{ task_id, revoked: true }`。
- `POST /admin/asr-corrections/{term_id}/approve`：body 增 `apply_to_existing: bool=false`；為 true 時 response 增 `task_id`。
- `POST /admin/asr-corrections/batch-restore`：body 範圍依 D-B 決定；回 `BackfillResponse`（affected_* + failed_chunk_ids）。
- Celery task：`detect_existing_episodes(self, show_id)`（新，`bind=True`）；`backfill_asr_corrections(self, show_id, term_id)`（改 `bind=True`）。兩者 PROGRESS meta 形狀一致：`{ current, total, phase, failed_chunk_ids }`。

**Failure modes：**

- 偵測 per-集 fail-open：單集 LLM / parse 失敗記 warning、計入失敗計數、不中斷整批（沿用 `detect_homophones` 既有 fail-open）。
- 套用 per-chunk isolation：單 chunk embedding 失敗記入 `failed_chunk_ids`、不中斷（既有行為）。
- 取消後：已 commit 部分保留；狀態 `REVOKED` + 「已處理 X/N」；救援走既有 restore / reject。
- status 查無 task_id（已過期 / 不存在）：回 `state='UNKNOWN'` + 說明 message，不丟 500。

**Acceptance criteria：**

- 後端 pytest：偵測既有集 task 進度回報（current/total 遞增）、fail-open 單集失敗不中斷；status endpoint 五態映射；cancel 後狀態 REVOKED；approve `apply_to_existing=true` 有 enqueue、false 不 enqueue；批次 restore 還原正確集。
- Prod smoke：對一個節目 dry-run 看成本 → 實跑 → 候選出現 + 進度條走完；approve 一條勾「順便套用」→ 既有集文字確實被改 + 可 restore；中途取消一個作業 → 狀態正確、已完成部分保留。

**Scope boundaries：**

- In scope：F6 偵測既有集入口、F8 觀測 / 取消 / 批次 restore、F-approve approve 觸發套用、LANGUAGE.md 兩條 canonical term。
- Out of scope：後台重構、浮水印 / 增量、偵測階段改文字、取消回滾、轉錄管線任何改動。

## Risks / Trade-offs

- **Celery result 過期**：`update_state` 進度存在 result backend，TTL 過了或 worker 重啟後查不到歷史。可接受——這些是「跑的時候看」的短期作業，非長期稽核；若日後要歷史紀錄再開 DB 表（對映 Non-Goal 的後台重構）。
- **取消不回滾可能讓操作者誤以為「沒事發生」**：用 `message` 明講「已處理 X/N」+ 引導用 restore，降低誤解。
- **D-B 概略 restore 誤還原**：若選 (b)，批次 restore 可能還原非本次作業改的集。UI 文案需警示「還原所有曾被校正的集」；若風險不可接受則選 (a)。
- **偵測既有集與轉錄 hook 偵測重複**：對「偵測上線後才轉錄進來的集」，F6 會再偵測一次（重複 LLM call）。`persist_candidates` dedup 擋掉重複候選，僅多花少量 token，符合 D6 取捨。
