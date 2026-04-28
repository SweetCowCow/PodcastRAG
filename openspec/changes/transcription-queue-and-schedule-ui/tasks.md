## 1. 後端：Reorder pending row position endpoint

- [x] 1.1 實作「Reorder pending row position」：在 backend/app/api/queue.py 新增 `PATCH /admin/queue/{queue_id}/position` endpoint，body schema 含 `position: int`，驗 status=pending 否則 409
- [x] 1.2 實作 position recompute：在單一 transaction 內處理 move-forward（`[new, old)` +1）/ move-backward（`(old, new]` -1）/ no-op，依「後端 position recompute：先位移再賦值」決定
- [x] 1.3 實作 clamp：若請求 position < min(pending.position) 或 > max(pending.position) 則 clamp 到邊界
- [x] 1.4 在 backend/app/schemas/queue.py 新增 `QueuePositionUpdate` schema（單欄位 `position: int`）
- [x] 1.5 補 pytest 測試 5 情境：move-forward、move-backward、clamp 過大、no-op、status=running 回 409

## 2. 前端：QueueTab 基本骨架（Admin page exposes a Transcription Queue tab）

- [x] 2.1 實作「Admin page exposes a Transcription Queue tab」+「5s polling 而非 WS」決定：新建 src/QueueTab.jsx functional component 接收 `lang` prop，內部用 useEffect setInterval 5000ms 同時 GET `/admin/queue` + `/admin/settings`，unmount 清 interval
- [x] 2.2 在 src/AdminPage.jsx 的 tabs 物件加 `'admin-queue': <QueueTab lang={lang} />`，順序排在 schedule 後 external-api 前
- [x] 2.3 在 src/Shared.jsx 的 admin nav items 加 `{ id: 'queue', icon: 'list'（或新 icon）, label: t ? '轉錄序列' : 'Queue' }`，位置匹配 admin tabs 順序；若 Icon 沒有 'list' 圖示，加新 SVG path
- [x] 2.4 在 src/App.jsx 的 admin route mapping 加 `admin-queue` page state value 對應到 AdminPage activePage
- [x] 2.5 渲染 5 個 status section（pending / running / completed / failed / cancelled）：每個 section header 顯示 status 名 + count，無 row 時顯「空」/「Empty」；row 顯示 episode title + show name + status badge + timestamps + error_message + celery_task_id（折疊）

## 3. 前端：Cancel / Force-cancel 按鈕（Pending rows expose Cancel button; Running rows expose Force Cancel button）

- [x] 3.1 實作「Pending rows expose Cancel button; Running rows expose Force Cancel button」requirement：pending row 加 「取消」/「Cancel」按鈕（secondary variant），onClick 直接 POST `/admin/queue/{id}/cancel`，成功後立即 setQueue 從 polling refresh 觸發；不加 confirm
- [x] 3.2 running row 加紅色「強制取消」/「Force Cancel」按鈕（danger variant），onClick 開 confirm dialog 顯示「確定要強制取消正在執行的轉錄嗎？此動作會中止 Whisper 呼叫且不可復原」/「Confirm force-cancel? This will abort the running Whisper call and cannot be undone.」+「確認」/「取消」二按鈕
- [x] 3.3 confirm 後 POST `/admin/queue/{id}/cancel?force=true`，請求進行中 confirm 按鈕 disabled；成功後關 dialog
- [x] 3.4 在 src/Shared.jsx 加 `<ConfirmDialog>` 共用元件（如尚無），接 `title` / `body` / `confirmLabel` / `cancelLabel` / `onConfirm` / `onCancel` / `loading` props

## 4. 前端：Retry / Ignore / Unignore（Failed rows expose Retry and Ignore; Ignored rows expose Unignore）

- [x] 4.1 實作「Failed rows expose Retry and Ignore; Ignored rows expose Unignore」requirement：failed row 且 ignored=false 加「重試」/「Retry」+「忽略」/「Ignore」二按鈕；Retry POST `/episodes/{episode_id}/transcribe`，Ignore POST `/admin/queue/{id}/ignore`
- [x] 4.2 row.ignored=true：整個 row 套用 muted 樣式（opacity 或灰底），按鈕改為「取消忽略」/「Unignore」呼叫 POST `/admin/queue/{id}/unignore`
- [x] 4.3 三個按鈕成功後靠 5s polling 自然刷新（不手動 setQueue），失敗 console.error + 顯示 inline 錯誤訊息

## 5. 前端：max_concurrent_transcriptions input（Tab header exposes max_concurrent_transcriptions input）

- [x] 5.1 實作「Tab header exposes max_concurrent_transcriptions input」+「Max concurrent input：debounce 500ms」決定：QueueTab 頂部加 number input，label「並行上限」/「Max Concurrent」，bind 到 `settings.max_concurrent_transcriptions`
- [x] 5.2 onChange 立即 setLocalValue（即時顯示），同時用 setTimeout debounce 500ms 後 PUT `/admin/settings` body `{"max_concurrent_transcriptions": value}`；若 user 在 500ms 內再次改值，clearTimeout 重新計時
- [x] 5.3 value > 3 時顯示 helper text「上限 3，受 worker concurrency 限制」/「Max 3, limited by worker concurrency」用 warning 色（TOKEN.warning 或紅）
- [x] 5.4 PUT 收到 422 時 revert local state 為 server response 值並顯示 backend error detail 在 input 下方

## 6. 前端：Drag reorder pending rows（Pending rows are draggable to reorder + Reorder pending row position）

- [x] 6.1 實作「Pending rows are draggable to reorder」requirement +「拖動排序：手刻 HTML5 native draggable + onDragOver / onDrop」決定：pending row 加 `draggable={true}` + `onDragStart`：`e.dataTransfer.setData('text/plain', row.id)`
- [x] 6.2 pending row 加 `onDragOver={e => e.preventDefault()}`（接受 drop）+ `onDrop`：取出 source row id，計算 target row（drop event 觸發在哪個 row），呼叫 helper `reorderPending(sourceId, targetPosition)`
- [x] 6.3 reorderPending：先樂觀更新 local pending 陣列順序，呼叫 PATCH `/admin/queue/{sourceId}/position` body `{"position": targetPosition}`；HTTP 200 不動，HTTP 4xx/5xx revert 並顯示錯誤
- [x] 6.4 拖動進行中（dragging state）整個 pending list 加 `pointer-events: none` 避免接受新拖動 until response 回
- [x] 6.5 running / completed / failed / cancelled section 不接受 drop（不掛 onDragOver / onDrop handler）

## 7. 前端：ScheduleTab modal 加 max_episodes_per_run（Schedule modal exposes max_episodes_per_run input）

- [x] 7.1 實作「Schedule modal exposes max_episodes_per_run input」requirement +「排程 modal `max_episodes_per_run` 為必填數字（match 後端 schema）」決定：在 src/AdminPage.jsx ScheduleTab 的 schedule edit modal 表單加 number input「每次最多轉錄集數」/「Max Episodes Per Run」，min=1
- [x] 7.2 編輯時預填 `schedule.max_episodes_per_run`；新建時預設 5（match 後端 default）
- [x] 7.3 Save 時把 `max_episodes_per_run` 包進 PUT/POST body

## 8. 前端：ScheduleTab 顯示 last_refresh_*（Schedule card displays last refresh status）

- [x] 8.1 實作「Schedule card displays last refresh status」requirement +「`last_refresh_*` 顯示：色彩依 status」決定：schedule 卡片底部新增 footer 區塊顯示 last_refresh：success → 綠 ✓ + 相對時間「N 分鐘前刷新」/「Refreshed N minutes ago」；failed → 紅 ✗ + 相對時間，hover 顯示 last_refresh_message；pending/null → 灰「尚未刷新」/「Not yet refreshed」
- [x] 8.2 在 src/AdminPage.jsx 內或 src/Shared.jsx 加 helper `formatRelativeTime(date, lang)` 算「N 秒前 / N 分鐘前 / N 小時前 / N 天前」
- [x] 8.3 schedule 編輯 modal 內加唯讀區塊顯示 last_refresh 三欄（at / status / message），新建模式不顯示

## 9. 前端：刪 show confirm 加 cascade count（Destructive actions require explicit confirmation 修改）

- [x] 9.1 修改「Destructive actions require explicit confirmation」requirement +「刪 show confirm：先抓 cascade 數」決定：點「Delete Show」按鈕後先呼叫 GET `/admin/queue` 過濾該 show_id，計算 pending_count 與 running_count
- [x] 9.2 confirm modal 內加 cascade-impact 行：N>0 或 M>0 時顯示「將同時取消 N 筆排隊中、M 筆執行中的轉錄任務」/「Will cancel N pending and M running transcription jobs」；N=0 且 M=0 時不顯示此行
- [x] 9.3 cascade fetch 不快取，每次點 Delete 重抓；fetching 期間 Delete 按鈕 disabled 顯 loading

## 10. 部署 + 驗收

- [ ] 10.1 push 到 GitHub main 觸發 Zeabur build，等 backend + frontend 部署成功
- [ ] 10.2 prod 驗收 — 基本：開 admin 切到「轉錄序列」tab，確認 5 個 section + max_concurrent input + polling 5s 觀察 row 變化
- [ ] 10.3 prod 驗收 — 操作：enqueue 5 集 → 對 pending 點「取消」確認回 200 + row 移到 cancelled section；對 running 點「強制取消」走 confirm dialog 確認 row 移到 cancelled
- [ ] 10.4 prod 驗收 — drag reorder：pending 區塊拖一個 row 到另一個位置上方，確認 PATCH 200 + UI 重排正確；嘗試拖到 running 區塊 confirm 不觸發 PATCH
- [ ] 10.5 prod 驗收 — schedule modal：開編輯 modal 確認 max_episodes_per_run 預填、修改後 save 成功；卡片底部顯示 last_refresh footer（success/failed/pending 三色）
- [ ] 10.6 prod 驗收 — 刪 show confirm：對有排隊任務的 show 點 Delete 確認 dialog 顯示「Will cancel N pending and M running...」
- [ ] 10.7 用 chrome-devtools-mcp 跑一遍中英雙語切換確認所有新文案正確
