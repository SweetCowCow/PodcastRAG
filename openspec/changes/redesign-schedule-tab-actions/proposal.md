## Why

ScheduleTab 上「同步」一詞同時被掛在「抓 RSS 更新集數清單」與「排隊轉錄（會燒 OpenAI quota）」兩個性質完全不同的動作上，使用者點「同步所有」時無法預期到底會不會花錢。同時 enable toggle 的語意混亂——它名義上是「節目啟用」，實際只影響「同步所有」要不要包含此節目，並不擋「立刻執行」，造成 toggle 像是壞掉的開關。本 change 一次解決這兩個 UX 問題。

## What Changes

- **BREAKING（UI 詞彙）**：UI 上「同步」一詞全面下架。
  - 「同步集數」→ **更新節目集數**
  - 「同步所有」→ **轉錄未完成集數**（批次按鈕，僅在有勾選時出現）
  - 「立刻執行」（單卡片快捷）保留
- **互動模型重構**：每個節目卡片左側加入 checkbox（類 Gmail 風格）。勾選任一節目後，頁面頂端顯示批次操作列「已選 N 個 / 更新節目集數 / 轉錄未完成集數 / 取消選取」。原「同步所有」按鈕移除。
- **單節目操作集中**：原本散在卡片右側的「更新節目集數 / 編輯排程 / 移除排程」收進「⋯」更多選單；保留「立刻執行」為主要可見按鈕。
- **enable toggle 從主畫面下架**：toggle 不再顯示於節目卡片，改名為「自動轉錄」並收進「編輯排程」modal，同時加入提示文案「待 cron 功能上線後生效」。`schedule.enabled` 欄位繼續保留於資料庫，給未來 cron change 直接接上。
- **批次轉錄安全網**：點擊「轉錄未完成集數」批次按鈕時跳一次 confirm「即將對 N 個節目排入轉錄，會消耗 OpenAI 額度，是否繼續？」；單節目「立刻執行」不擋。
- **批次轉錄範圍規則**：每個被勾選節目沿用自己 `schedule.max_episodes` 設定（與目前單節目「立刻執行」一致行為）。

## Non-Goals

- **不實作 cron / Celery Beat**：自動排程執行（依 frequency / run_time 真的定時跑）刻意排除，留給未來獨立 change。本 change 仍保留 `frequency`、`run_time`、`enabled` 欄位以利未來接續。
- **不新增後端 endpoint**：批次操作由前端 fan-out 多個現有 endpoint 請求（`POST /shows/{id}/sync`、`POST /shows/{id}/transcribe-latest`），不引入 `/admin/batch-*` 類聚合端點。
- **不變更後端排程資料模型**：`show_schedules` 表結構不動，僅 UI 對 `enabled` 欄位的讀寫位置改變。
- **不重新設計「新增排程」表單**與「編輯排程」modal 的版面（除了在 modal 內新增「自動轉錄」欄位）。

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `admin-show-management-ui`: 節目卡片按鈕集合、批次選取互動、enable toggle 位置全部變更；單節目按鈕從 5 顆改為「立刻執行 + ⋯ 選單」。
- `transcription-schedule`: `enabled` 欄位的 UI 暴露點從卡片 toggle 改為「編輯排程」modal 內欄位；行為語意從「同步所有過濾條件」變更為「未來自動排程旗標」（目前無 runtime 影響但仍可讀寫）。

## Impact

- Affected specs: `admin-show-management-ui`（MODIFIED）、`transcription-schedule`（MODIFIED）
- Affected code:
  - Modified:
    - src/AdminPage.jsx（ScheduleTab 全段重寫：移除 handleSyncAll 改為 handleBatchUpdate / handleBatchTranscribe；新增 selection state；按鈕重命名；toggle 移到 edit modal）
  - New: （無新檔案）
  - Removed: （無刪除檔案）
- 後端：不變更（沿用現有 `POST /shows/{id}/sync` 與 `POST /shows/{id}/transcribe-latest`）
- 資料庫：不變更（`show_schedules.enabled` 欄位保留）
- 文件：`docs/case-studies/sync-naming-redesign.md` 已先行寫入記錄此 UX 拆解過程，與本 change 互為參照
