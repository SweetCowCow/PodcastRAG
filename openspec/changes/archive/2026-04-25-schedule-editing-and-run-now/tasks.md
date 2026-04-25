## 1. 後端：共用 sync helper

- [x] 1.1 實作 Requirement: Sync logic is reusable across endpoints——在 `backend/app/services/` 新增 `sync.py`，把既有 `backend/app/api/shows.py` 內 `sync_show` 函式裡的 upsert 迴圈（fetch_and_parse → 逐集查 existing_by_guid → 新增/更新 → flush → count）抽成 `async def sync_show_episodes(show_id: uuid.UUID, db: AsyncSession) -> dict`（回傳 `{added, updated, total}`）；函式內部 raise `RssParseError` 給 caller 處理 HTTP 400
- [x] 1.2 修改 `backend/app/api/shows.py` 的 `POST /shows/{show_id}/sync` handler：改為呼叫 `sync_show_episodes`，仍然回傳既有 `SyncResponse` 格式，並把 `RssParseError` 轉成 HTTP 400

## 2. 後端：transcribe-latest 端點

- [x] 2.1 實作 Requirement: Transcribe-latest endpoint syncs then enqueues newest N unfinished episodes——在 `backend/app/schemas/sync.py`（或合適位置）新增 `TranscribeLatestResponse` Pydantic schema：`queued: int`、`synced: SyncResponse`
- [x] 2.2 在 `backend/app/api/transcripts.py` 新增 `POST /shows/{show_id}/transcribe-latest`：
  - 接收 `show_id: uuid.UUID` path param、`max_episodes: int | None = Query(default=None, ge=1)`
  - 查 Show；不存在回 404
  - 呼叫 `sync_show_episodes(show_id, db)` 取得 `{added, updated, total}`；`RssParseError` 轉 HTTP 400
  - 決定 effective max：query `max_episodes` > `show_schedules.max_episodes`（> 0 才算）> 5
  - `SELECT episodes LEFT JOIN transcripts WHERE show_id = ? AND (transcripts.id IS NULL OR transcripts.status != 'completed') ORDER BY episodes.published_at DESC LIMIT effective_max`
  - 逐集：若 transcript 不存在新增 status=pending；若存在且 != completed 重設 status=pending、清空 error_message；flush；呼叫 `enqueue_transcription(ep.id)`；累加 queued
  - 回 202 + `TranscribeLatestResponse(queued=queued, synced=SyncResponse(added=added, updated=updated, total=total))`

## 3. 前端：FormModal 共用元件

- [x] 3.1 實作 Requirement: FormModal shared component——在 `src/Shared.jsx` 新增 `FormModal` 元件：接收 `{ open, title, children, confirmLabel, cancelLabel, onConfirm, onCancel, submitDisabled }`；open=false 回 null；open=true 渲染全屏半透明 backdrop（點擊 = onCancel）+ 置中卡片（TOKEN.surface bg、TOKEN.surfaceBorder border、radius 14）；卡片結構：title（fontWeight 700，TOKEN.text）→ `{children}` 區塊（min-height 留白）→ 按鈕列（ghost Cancel + primary Confirm，Confirm 吃 submitDisabled）
- [x] 3.2 在 Shared.jsx 檔案末尾的 `Object.assign(window, { ... })` 加入 `FormModal` export

## 4. 前端：Edit Schedule button + modal

- [x] 4.1 實作 Requirement: Edit Schedule opens a form modal and persists via PUT——在 `src/AdminPage.jsx` 的 `ScheduleTab` 元件新增 state：`const [editState, setEditState] = React.useState(null)`（shape：`{ item, form: { frequency, run_time, whisper_model, max_episodes } }` 或 null）
- [x] 4.2 新增 `handleOpenEdit(item)`：從 `item.schedule` 讀出四個欄位，setEditState({ item, form: {...} })
- [x] 4.3 新增 `handleSaveEdit()`：fetch `PUT ${API_BASE}/shows/${editState.item.show_id}/schedule` 帶 editState.form 全部四個欄位；成功時 setEditState(null) + loadSchedules()；失敗 alert
- [x] 4.4 在卡片的操作按鈕列加 `<Btn size="sm" variant="ghost" icon="settings" onClick={() => handleOpenEdit(item)}>` 顯示「編輯排程」/「Edit Schedule」，僅在 `item.schedule` 存在時渲染
- [x] 4.5 在 `ScheduleTab` 渲染結尾新增 `<FormModal open={editState !== null} title="編輯排程/Edit Schedule" confirmLabel="儲存/Save" cancelLabel="取消/Cancel" onConfirm={handleSaveEdit} onCancel={() => setEditState(null)}>`；children 放四個表單欄位（frequency select、run_time time input、whisper_model select、max_episodes number），全部使用 editState?.form 與 setEditState 更新

## 5. 前端：Run Now button

- [x] 5.1 實作 Requirement: Run Now triggers transcribe-latest for a single show——在 ScheduleTab 新增 state：`const [runningId, setRunningId] = React.useState(null)`
- [x] 5.2 新增 `handleRunNow(item)`：setRunningId(item.show_id) → fetch `POST ${API_BASE}/shows/${item.show_id}/transcribe-latest` → 成功讀取 `{queued, synced}` alert「已排入 {queued} 集（新增 {synced.added}/更新 {synced.updated}）」；失敗 alert 錯誤；finally setRunningId(null) + loadSchedules()
- [x] 5.3 在卡片的操作按鈕列加 `<Btn size="sm" variant="primary" icon="play" onClick={() => handleRunNow(item)} disabled={runningId === item.show_id}>` 顯示「立刻執行」/「Run Now」，僅在 `item.schedule` 存在時渲染；按鈕 disable 時文字改顯示「執行中...」/「Running...」

## 6. 前端：Sync All 改用 transcribe-latest

- [x] 6.1 實作 Requirement: Sync All uses transcribe-latest across enabled shows——修改 `handleSyncAll`：filter enabled shows → `Promise.all(enabled.map(s => fetch(POST ${API_BASE}/shows/${s.show_id}/transcribe-latest)))`（取代既有 transcribe-all）→ 成功後 alert「已對 N 個啟用節目排入轉錄」→ loadSchedules()；錯誤照現有處理

## 7. 驗證

- [x] 7.1 `curl -X POST http://localhost:8000/shows/{id}/transcribe-latest?max_episodes=2`，確認回 202 + 回應 body 含 `queued` 與 `synced.added`/`synced.updated`；檢查 DB 中對應 show 的 episodes 有 2 集 transcript.status=pending 且 published_at 最新的兩集
- [x] 7.2 再次呼叫同一 show 的 transcribe-latest（無 query param），確認使用 schedule.max_episodes（若有設）；若節目沒 schedule 改為預設 5
- [x] 7.3 在瀏覽器後台「轉錄排程」頁：點「編輯排程」→ modal 彈出並預填目前值 → 改 max_episodes 後儲存 → 重新整理後卡片顯示新值
- [x] 7.4 點「立刻執行」按鈕：按鈕 disabled → 短時間後 alert 顯示 queued 數字 → 卡片的 pending_count 更新
- [x] 7.5 點「同步所有」：只有 enabled 的節目被打 transcribe-latest（DB 中非 enabled 節目不新增 pending transcript）
- [x] 7.6 點「取消」或 modal backdrop：modal 關閉 且 DevTools Network 面板確認沒發出 PUT request
