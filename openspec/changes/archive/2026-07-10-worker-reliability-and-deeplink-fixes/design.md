## Context

EP326 匯入卡死事故的 RCA 證實：worker 失敗處理鏈有三個疊加缺陷（NameError 吞收尾、無終止狀態、dispatcher 單一任務型別假設），前端 deep-link 有一個分頁假設缺陷。四者都已對源碼定位。本 change 跨 worker（tasks / dispatcher / cron_tick）、backend API（episodes）、前端（App / QueryPage）三個層面，需要先定案幾個技術決策再實作。

現況約束：
- `transcription_queue` 表無失敗計數欄位（現有欄位：status / error_message / whisper_model / celery_task_id / dispatched_at 等）。
- `status='failed'` 本身就是 terminal（orphan-revert 只動 running、dispatcher 只 pop pending）；無限迴圈的成因是 row 卡在 running 被 revert 回 pending，而非 failed 被復活。
- Zeabur 部署時 entrypoint 會自動跑 alembic upgrade head（依 2026-06 migration 紀律，additive column 安全）。
- 匯入來源 JSON 在 Jacky 本機，系統端無法自行重跑匯入。

## Goals / Non-Goals

**Goals**
1. permanent ASR 失敗一次到位標 terminal failed（狀態收尾不被記錄失敗連帶吞掉）。
2. 任何 row（含 import 路徑）反覆「開始→遺失→revert」達門檻即停，後台可見可手動 retry。
3. dispatcher 對 `external:` row 永不派 ASR。
4. 任何歷史集的 `?show_id=&episode_id=&t=` deep-link 都能落地；查詢頁計數不再誤導。

**Non-Goals**
- 不自動重匯 external row、不動 B1（re-sync 失效 storage key）、不重構 episodes 列表載入策略、不改 orphan-revert / stale-detect 偵測本體。

## Decisions

**D1 — NameError 修法：狀態收尾先行，記錄後行且 fail-open**
`_run` 的 PERMANENT_ERRORS 區塊改為：(a) 先完成 transcript 標 failed + `_mark_queue_finished(failed)`；(b) 再呼叫 `record_task_failure`，包 try/except 吞例外只留 log；(c) `retry_count` 固定傳 0（module-level 函式無 Celery task context；真正的 retry 計數屬 on_failure hook 的職責，該處有 `self`）。
理由：狀態正確性 > 監控記錄完整性；順序對調後任一半損壞都不再產生無限重派。

**D2 — 連續失敗終止：`failure_count` 欄位 + orphan-revert 時遞增**
`transcription_queue` 加 `failure_count INTEGER NOT NULL DEFAULT 0`（additive migration）。orphan-revert 把 running row 打回 pending 時 `failure_count += 1`；達門檻（常數 `MAX_CONSECUTIVE_FAILURES = 3`）改標 `failed`，error_message 註明「連續 3 次未完成，已停止自動重試」。手動 retry（既有後台按鈕）將 failure_count 歸零。
理由：orphan-revert 是「task 遺失」唯一的復活入口，在入口計數即可涵蓋 import task 遺失、worker 重啟丟 task 等所有無限循環路徑；選 row 欄位而非另建表，因為計數生命週期與 row 完全一致。門檻 3 = 允許兩次偶發容器重啟，第三次視為系統性問題。

**D3 — dispatcher 短路 external: row**
`_try_pop_one` pop 出 row 後（或 SQL 條件內）檢查 `whisper_model` 是否以 `external:` 開頭：是 → 直接 UPDATE `status='failed'`、error_message='外部匯入集，系統無法重跑 ASR；請重新執行 transcript-import'，不送 celery task。
理由：dispatcher 是派工唯一入口，在此短路即可保證不漏；標 failed（而非留 pending）讓後台可見且不再被 pop。

**D4 — 新增單集查詢 GET /episodes/{episode_id}**
`backend/app/api/episodes.py` 新增 route：回 `EpisodeResponse`（含 transcript_status，同列表 shape），404 當 episode 不存在。`App.jsx` deep-link receiver 改為：`/shows` 取 show meta（不變）+ 新 endpoint 取單集，移除「抓列表再 find」。
理由：單集查詢是正確原語；列表 + find 在任何分頁參數下都是錯的。公開讀取端點（與列表同權限層級），無 auth 變更。

**D5 — 查詢頁計數改用 show.transcribed_count**
`QueryPage.jsx` 的 `epCount` 直接用 `show.transcribed_count`（頂部 badge 既有來源，後端統計為準），移除「已載入分頁 filter 計數」邏輯。
理由：前端已載入分頁永遠是子集，任何本地計數都會低估；兩處數字來源統一消除矛盾顯示。

## Risks / Trade-offs

- **D2 誤殺慢任務**：長集數處理 > orphan-revert 門檻時間會被 revert 計 1 次失敗；但門檻 3 次緩衝 + 手動 retry 可恢復，可接受。監控點：上線後一週觀察 failure_count>=1 的 row 分佈。
- **D3 對既有 completed external row 無影響**（dispatcher 只 pop pending），風險僅在未來匯入中斷情境——正是要保護的情境。
- **D4 新端點無分頁 / 無 N+1 疑慮**（單鍵查詢）；快取層不動。
- **alembic migration**：單一 additive column + server_default，符合部署 entrypoint 自動 upgrade 的安全模式；不需雙寫過渡。

## Migration Plan

1. alembic revision：`transcription_queue` 加 `failure_count`（NOT NULL DEFAULT 0）——與程式碼同一 commit 部署，entrypoint 自動 upgrade。
2. 無資料 backfill 需求（既有 row 起算 0 合理）。
3. 回滾：revert commit 即可；欄位留存不影響舊程式。

## Open Questions

- 門檻 3 次是否合適由 prod 一週觀察定案（可調常數，不做 env 設定）。
- deep-link prod smoke 集數樣本：兩新節目各挑一集「第 51 集以後」的舊集（實作時從 DB 取）。
