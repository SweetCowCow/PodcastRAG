## Why

使用者目前無法在前端刪除節目、移除排程或手動同步 RSS 新集數——這些後端端點（`DELETE /shows/{id}`、`DELETE /shows/{id}/schedule`、`POST /shows/{id}/sync`）早已存在但沒有 UI 串接。部分刪除操作會造成不可逆資料損失（CASCADE 刪 episodes/transcripts/chunks），需要二次確認防誤觸。

另外，節目新增/刪除屬管理性操作，應集中在後台；一般使用者的節目選擇頁維持唯讀，避免誤操作。

## What Changes

- 在後台「轉錄排程管理」每張節目卡片加操作按鈕：
  - **刪除節目**：呼叫 `DELETE /shows/{id}`（會 CASCADE 刪除 episodes、transcripts、chunks、schedule）
  - **同步新集數**：呼叫 `POST /shows/{id}/sync`，顯示本次新增/更新集數
  - **移除排程**：呼叫 `DELETE /shows/{id}/schedule`，僅在 `item.schedule !== null` 時顯示
- 新增一個共用的「確認刪除」modal 元件，放在 `Shared.jsx`：
  - 所有刪除操作（刪節目、刪排程）都必須經此 modal 使用者按下「確認刪除」才會呼叫 API
  - 同步新集數不需要 modal（非破壞性操作）
- 所有操作完成後 re-fetch `GET /admin/schedules` 以更新清單

## Non-Goals

- 不新增/修改任何後端端點（Change A 範圍純前端）
- 不在節目選擇頁（`PodcastSelect.jsx`）加任何管理按鈕——前端維持唯讀
- 不處理排程編輯（頻率、時間、Whisper model 等調整）——留給 Change B
- 不處理「立刻執行」或單集觸發轉錄——留給 Change B
- 不處理 per-episode 進度/錯誤顯示——留給 Change C

## Capabilities

### New Capabilities

- `admin-show-management-ui`: 後台節目管理 UI 的行為規格，涵蓋刪除節目、同步新集數、移除排程、以及刪除類操作的確認 modal 流程

### Modified Capabilities

（無——後端行為不變；前端僅對既有端點增加 UI 入口）

## Impact

- 影響檔案：
  - `src/AdminPage.jsx`（`ScheduleTab` 元件加三顆按鈕與對應 handler）
  - `src/Shared.jsx`（新增 `ConfirmModal` 共用元件並 export 到 window）
- 不影響後端、資料庫、Alembic migration
- 不影響 `PodcastSelect.jsx`、`QueryPage.jsx`、`TranscriptPage.jsx`
