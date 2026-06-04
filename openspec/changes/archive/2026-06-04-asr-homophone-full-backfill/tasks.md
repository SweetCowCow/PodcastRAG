## 1. 後端：偵測原有集數（F6）

- [x] 1.1 新增 `services/asr_detection_backfill.py` 批次驅動器：給定 show_id，查該節目全部有逐字稿的既有集，per 集呼叫 `detect_homophones` + `persist_candidates`，回傳累計 `{ processed, total, persisted, failed_episode_ids }`。per-集 fail-open（單集失敗記 warning + 計入 failed、不中斷）。並發度先用序列實作（design D-A：預設序列，並發列為後續優化）。完成標準：單元測試證明三集（其中一集偵測拋錯）→ processed=3、failed=1、其餘兩集候選有 persist。（覆蓋 spec requirement: "Detection backfill over a show's existing episodes"）
- [x] 1.2 `workers/tasks.py` 新增 `detect_existing_episodes(self, show_id)`，`bind=True`，呼叫 1.1 driver，每處理完一集 `self.update_state(state='PROGRESS', meta={current,total,phase,failed_chunk_ids})`。完成標準：測試以 fake driver 驗證 update_state 的 current 隨集數遞增、終態 return dict 含 persisted/failed。
- [x] 1.3 `api/admin/asr_corrections.py` 新增 `POST /detect-existing`：body `{ show_id, dry_run=true }`。dry_run=true 用既有 `estimate_detection_cost`（先查該節目既有集 id 清單）回成本估；dry_run=false enqueue 1.2 task 回 `task_id`。`schemas/asr_correction.py` 加對應 request + dry-run response model。完成標準：測試 dry_run=true 不 enqueue、回 episode_count/estimated_cost_usd；dry_run=false 回 task_id。

## 2. 後端：背景作業可觀測 / 可取消（F8）

- [x] 2.1 `workers/tasks.py` 的 `backfill_asr_corrections` 改 `bind=True`，每處理完一份逐字稿 `update_state` 報 `{current,total,phase,failed_chunk_ids}`（current=已處理 transcript 數）。完成標準：測試驗證套用作業跑兩份逐字稿時 current 由 1→2、failed_chunk_ids 累積進 meta。（覆蓋 spec requirement: "Backfill jobs report progress and are cancellable"）
- [x] 2.2 新增 `GET /backfill-status/{task_id}`：用 `AsyncResult` 把 PENDING/PROGRESS/SUCCESS/FAILURE/REVOKED/未知 六種情況映射成固定 response `{ state, current, total, phase, failed_chunk_ids, message }`（design D3，禁止直接回 raw state；查無 task 回 state='UNKNOWN' 不丟 500）。`schemas` 加 status response model。完成標準：測試六態各自映射正確、unknown 不 raise。
- [x] 2.3 新增 `POST /backfill-cancel/{task_id}`：`AsyncResult.revoke(terminate=True, signal='SIGTERM')`，回 `{ task_id, revoked:true }`。完成標準：測試呼叫後 revoke 被觸發；對映 design D4 取消不回滾語意（已 commit 部分保留，由 2.1 的 per-unit commit 保證）。

## 3. 後端：批次 restore（F8）

- [x] 3.1 決定 design D-B 範圍：若已有「套用 task → 涉及 episode 集合」的落盤紀錄則用精準範圍，否則用「所有 `transcript.original_content IS NOT NULL` 的集」概略範圍（apply 時依現況擇一並在 PR 註明）。在 `services/asr_correction.py` 實作批次 restore（逐集呼叫既有 `restore_episode`），新增 `POST /batch-restore` endpoint 回 `BackfillResponse`（affected_* + failed_chunk_ids）。完成標準：測試對兩集已校正內容批次 restore → 兩集 segment/content 還原回 snapshot、affected_transcripts=2。（覆蓋 spec requirement: "Batch restore of episodes touched by rule application"）

## 4. 後端：approve 順便套用原有集數（F-approve）

- [x] 4.1 `approve_candidate` 的 `AsrCandidateApprove` schema 加 `apply_to_existing: bool=false`；為 true 時 approve 成功後 enqueue 帶該 `term_id` 的 `backfill_asr_corrections`，response 加回 `task_id`；為 false 維持現行只設 approved+enabled。完成標準：測試 apply_to_existing=true → rule approved 且有 enqueue 帶 term_id、回 task_id；=false → 不 enqueue。（覆蓋 spec requirement: "Approving a candidate can apply it to existing episodes"）

## 5. 前端：後台 UI（F8 UI + F-approve UI）

- [x] 5.1 `src/AdminPage.jsx` ASR tab 加「偵測既有集」：選節目 → 先打 dry_run 顯示成本估（集數 / 估 token / 估 USD）→ 確認 modal → 打 dry_run=false 取得 task_id。完成標準：瀏覽器驗證點擊後出現成本估、確認後作業啟動。（覆蓋 spec requirement: "Admin UI triggers detection over a show's existing episodes"）
- [x] 5.2 `src/AdminPage.jsx` 加背景作業狀態區：輪詢 `/backfill-status/{task_id}` 顯示 current/total 進度條 + failed_chunk_ids 清單 + 取消按鈕（打 `/backfill-cancel`）。完成標準：瀏覽器驗證進度條隨輪詢更新、取消按鈕觸發後狀態轉「已取消，已處理 X/N」。（覆蓋 spec requirement: "Admin UI shows backfill progress, failures, and cancellation"）
- [x] 5.3 `src/AdminPage.jsx` 加批次 restore 按鈕（打 `/batch-restore`）與 approve 候選時的「同時套用到既有集」勾選（帶 apply_to_existing）。所有新文案提供 zh/en 雙語、用 TOKEN design system。完成標準：瀏覽器驗證勾選 approve 後既有集文字被改 + 批次 restore 可還原。（覆蓋 spec requirement: "Admin UI offers batch restore and approve-and-apply"）

## 6. 詞彙

- [x] 6.1 `openspec/LANGUAGE.md` 新增兩條 canonical term：「偵測原有集數」（對既有逐字稿跑 LLM 偵測產候選、不改文字）與「套用原有集數」（把已 approve 規則字面套到既有逐字稿），各含 definition / avoid（「回填」）/ why。完成標準：兩條 entry 存在且格式與既有 term 一致。

## 7. 驗證

- [x] 7.1 後端 pytest 全綠：涵蓋 1.1 偵測 fail-open、1.2/2.1 進度遞增、2.2 status 六態映射、2.3 cancel、3.1 批次 restore、4.1 approve apply_to_existing 兩分支。
- [x] 7.2 Prod smoke（推 Zeabur 後）：對一個節目 dry-run 看成本 → 實跑 → 候選出現 + 進度條走完；approve 一條勾「順便套用」→ 既有集文字確實被改且可 restore；中途取消一個作業 → 狀態 REVOKED、已完成部分保留。結果記入對應 case study。
