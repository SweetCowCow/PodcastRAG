## 1. 共用元件：ConfirmModal

- [x] 1.1 實作 Requirement: Destructive actions require explicit confirmation——在 `src/Shared.jsx` 新增 `ConfirmModal` 元件：props 為 `{ open: bool, title: string, message: string|ReactNode, confirmLabel: string, cancelLabel: string, danger: bool, onConfirm: () => void, onCancel: () => void }`；`open === false` 時不渲染；`open === true` 時渲染全屏半透明 backdrop + 置中卡片（`TOKEN.surface` 背景、`TOKEN.surfaceBorder` 邊框）；卡片包含 title（`TOKEN.text`、fontWeight 700）、message 區域、兩顆按鈕（`Confirm` 用 `<Btn variant="danger">` 當 `danger===true` 否則 `primary`、`Cancel` 用 `<Btn variant="ghost">`）；點 backdrop 呼叫 `onCancel`
- [x] 1.2 在 `src/Shared.jsx` 檔案末尾的 `Object.assign(window, { ... })` 加入 `ConfirmModal` export

## 2. ScheduleTab：三顆操作按鈕與 handlers

- [x] 2.1 在 `src/AdminPage.jsx` 的 `ScheduleTab` 元件新增 state：`const [confirmState, setConfirmState] = React.useState(null)`（shape：`{ kind: 'delete-show'|'remove-schedule', item }` 或 `null`）；以及 `const [syncingId, setSyncingId] = React.useState(null)`
- [x] 2.2 實作 Requirement: Sync Episodes is non-destructive and requires no confirmation——新增 `handleSyncShow(item)`：`setSyncingId(item.show_id)` → `fetch POST ${API_BASE}/shows/${item.show_id}/sync`；成功回 200 時讀取 `{added, updated, total}` 並用 `alert` 顯示「已同步：新增 X 集、更新 Y 集」；失敗時 alert 錯誤訊息；最後 `setSyncingId(null)` 並呼叫 `loadSchedules()`
- [x] 2.3 實作 Requirement: Remove Schedule deletes only the schedule row——新增 `handleRemoveSchedule(item)`：呼叫 `fetch DELETE ${API_BASE}/shows/${item.show_id}/schedule`；成功（204）時呼叫 `loadSchedules()`；失敗時 alert
- [x] 2.4 實作 Requirement: Admin schedule card exposes show-level actions——新增 `handleDeleteShow(item)`：呼叫 `fetch DELETE ${API_BASE}/shows/${item.show_id}`；成功（204）時呼叫 `loadSchedules()`；失敗時 alert
- [x] 2.5 在每張卡片右側加操作列：`<Btn size="sm" variant="secondary" icon="refresh" onClick={() => handleSyncShow(item)} disabled={syncingId === item.show_id}>` 顯示「同步集數」/「Sync Episodes」（中英雙語）；`<Btn size="sm" variant="ghost" icon="trash" onClick={() => setConfirmState({ kind: 'remove-schedule', item })}>` 顯示「移除排程」，僅在 `item.schedule` 存在時渲染；`<Btn size="sm" variant="danger" icon="trash" onClick={() => setConfirmState({ kind: 'delete-show', item })}>` 顯示「刪除節目」
- [x] 2.6 在 `ScheduleTab` 渲染結尾加 `<ConfirmModal>`：`open={confirmState !== null}`；`title`、`message`、`confirmLabel` 依 `confirmState.kind` 切換：
  - `delete-show`：title「刪除節目」、message「即將刪除節目「{show_title}」及其所有 {episode_count} 集逐字稿、排程設定。此操作不可復原。」、confirmLabel「確認刪除」、`danger=true`
  - `remove-schedule`：title「移除排程」、message「即將移除節目「{show_title}」的轉錄排程設定。節目與已轉錄集數不受影響。」、confirmLabel「確認移除」、`danger=true`
  onConfirm: 依 kind 呼叫 `handleDeleteShow` 或 `handleRemoveSchedule`，然後 `setConfirmState(null)`；onCancel: 只呼叫 `setConfirmState(null)`
- [x] 2.7 中英雙語：所有新增的按鈕 label、modal 文字皆支援 `lang === 'zh'` 與 `lang === 'en'` 兩種版本，參考檔案中既有的 `t` 判斷寫法

## 3. PodcastSelect 驗證

- [x] 3.1 實作 Requirement: PodcastSelect remains read-only——閱讀 `src/PodcastSelect.jsx`，確認沒有任何管理按鈕（新增、編輯、刪除 show）；若發現有，移除之；若確認沒有，此 task 僅需在本 tasks.md 記錄「已確認」即可完成

## 4. 驗證

- [x] 4.1 瀏覽器開啟 `http://localhost:8080/PodcastRAG.html` → 後台 → 轉錄排程，確認每張卡片顯示三顆操作按鈕（無 schedule 的卡片不顯示「移除排程」）
- [x] 4.2 點「同步集數」按鈕，確認：按鈕在請求中被 disable；成功後 alert 顯示 added/updated 數字；卡片的 `pending_count` 更新
- [x] 4.3 點「移除排程」按鈕，確認：跳出確認 modal；點「取消」無網路請求；再點按鈕 → 確認 → 卡片重新整理後 `schedule` 變成 null，「未設定」badge 出現
- [x] 4.4 點「刪除節目」按鈕，確認：跳出確認 modal 且訊息包含節目名稱；點「確認刪除」後卡片從列表消失；`curl http://localhost:8000/shows/{id}` 回 404；DB 中該節目的 episodes/transcripts/schedule 都被 CASCADE 刪除
- [x] 4.5 打開 `PodcastSelect` 頁（節目選擇），確認沒有新增/刪除/編輯按鈕
