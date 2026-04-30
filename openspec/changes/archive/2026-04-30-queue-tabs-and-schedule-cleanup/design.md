## Context

轉錄佇列分頁（`src/QueueTab.jsx`）目前以五個並排 section 渲染所有 status，列數一多需大量捲動，且使用者通常一次只關注「進行中」「失敗待處理」「歷史完成」其一。後台 `/admin/queue` 已是聚合回傳 `{pending, running, completed, failed, cancelled}` 五桶，**前端純切版即可達成三分頁，不需後端改動**。

排程設定方面，後端 spec 與 cron tick (`backend/app/workers/cron_tick.py`) 已限制 `frequency` 為 `daily / weekly / manual` 三值，但前端 select (`src/AdminPage.jsx:842, 1091`) 仍提供 `hourly` 選項，造成可儲存「實際永遠不會觸發」的設定。同時 weekly 觸發在 `_is_due` 寫死 `weekday == 0`（週一），無法配置星期。

`show_schedules` 表現有欄位（`backend/app/models/show_schedule.py`）：`enabled`、`frequency`、`run_time`、`whisper_model`、`max_episodes_per_run`、`last_refresh_*`。本次新增 `day_of_week INTEGER NOT NULL DEFAULT 0` 即可支援 weekly 配置。

## Goals / Non-Goals

**Goals:**

- 轉錄佇列分頁切成三個子分頁（`排隊+執行 / 完成 / 失敗+取消`），保留所有列內動作（拖曳、重試、忽略、強制取消、cancel pending、force-cancel running）。
- 移除 UI 殘留的 `hourly` 選項；既有 `frequency='hourly'` 列在前端讀取時 fallback 顯示為 `daily`。
- 排程編輯 modal 改為條件式欄位渲染：weekly 多顯示 day picker、manual 隱藏執行時間與星期。
- `show_schedules` 加 `day_of_week` 欄位；`_is_due` weekly 分支改讀此欄位。
- 動態提示文案讓使用者一眼看懂「什麼時候會跑」。

**Non-Goals:**

- 不改後端 `/admin/queue` API、不分頁載入、不加跨 tab 批次動作（如「清空已完成」）。
- 不改 `transcription_queue` schema、不調整去重邏輯、不讓「完成」分頁顯示歷史多筆紀錄（unique 約束維持）。
- 不對既有 `frequency='hourly'` row 做自動寫回 — 只在前端顯示時 fallback，等使用者下次儲存才實際更新。
- 不改 `enabled` toggle 行為、不改「立即執行」按鈕邏輯、不改「同步所有」批次按鈕。
- weekday 編號慣例不重新討論：沿用 Python `datetime.weekday()`（週一=0，週日=6），與既有 `cron_tick.py:213` 一致。
- 不改 backend 預設值結構之外的 schedule defaults（仍 `frequency='daily'`, `run_time='06:00'`）。

## Decisions

### Frontend 切分頁 vs 後端分頁

**選擇**：前端切分頁（state-only），後端 `/admin/queue` 不動。

**理由**：使用者明確要求純前端切版；`/admin/queue` 已是 5 桶聚合回傳，列數規模在後台單機操作下不構成效能問題（每 5 秒輪詢仍可接受）。後端分頁需新增 query string、改 schema、改前端輪詢策略，成本不對等。

**Alternatives considered**：後端分頁（query `?status=pending,running`）— 拒絕，理由如上。

### Sub-tab 切換用本地 state 而非 URL route

**選擇**：在 `QueueTab.jsx` 內新增 `const [activeTab, setActiveTab] = useState('active')`，三值 `'active' | 'completed' | 'closed'`；不註冊新 page route。

**理由**：admin tab 路由（`page === 'admin-queue'`）由 `App.jsx` 控制，sub-tab 屬於 QueueTab 內部 UI 狀態，混入全域 page state 會破壞既有 routing convention。重新整理回到預設 sub-tab 對使用者影響低。

**Alternatives considered**：URL hash（`#completed`）— 不必要，後台頁面不需深連結分享。

### 子分頁命名

**選擇**：

| activeTab 值 | 中文標籤 | 英文標籤 | 內含 status |
|---|---|---|---|
| `active` | 進行中 | Active | pending + running |
| `completed` | 已完成 | Completed | completed |
| `closed` | 已結束 | Closed | failed + cancelled |

**理由**：使用者原始描述用「排隊+執行」「完成」「失敗+取消」描述，但 UI tab 標籤需更精煉。`active` 涵蓋「正在排隊或執行」、`closed` 涵蓋「終止狀態（成功外）」。Badge 計數顯示在 tab 標題後（例：`進行中 (3)`）。

**Alternatives considered**：直接用「排隊+執行 / 完成 / 失敗+取消」三字長標籤 — 拒絕，太長且分隔符不易閱讀。

### 子分頁內 section 是否保留小標題

**選擇**：

- `active` 分頁：保留 `排隊中（可拖動排序）` 與 `執行中` 兩個 section 小標題（因兩 status 行為差異大：pending 可拖、running 顯示 force cancel）。
- `closed` 分頁：保留 `失敗` 與 `已取消` 兩個 section 小標題（failed 有 retry/ignore 按鈕，cancelled 唯讀）。
- `completed` 分頁：單一 status 不需 section 小標題，直接列表。

**理由**：跨 status 視覺區隔有意義時保留分組；單一 status 不需重複標題。

### Weekday 欄位編號

**選擇**：Python `datetime.weekday()` 慣例（週一=0, 週日=6），DB 型別 `INTEGER NOT NULL DEFAULT 0`。

**理由**：`cron_tick.py:213` 既有 `weekday == 0` 已使用此慣例；保持一致最少改動，且 default=0 讓既有 row 行為不變（仍週一觸發）。

**Alternatives considered**：ISO 8601（週一=1）— 多一層轉換無收益；JS 慣例（週日=0）— 與後端不一致。

### 既有 hourly row 處理：前端 fallback、不寫回

**選擇**：`AdminPage.jsx` 在初始化 form state 時，若 `item.schedule.frequency` 不在 `[daily, weekly, manual]` 內，改填 `daily`；不主動 PUT 回後端，使用者下次儲存才寫入。Modal 開啟時若偵測到 fallback，於頻率 select 下方顯示一行警示文案：「原設定 `hourly` 已停用，已改為每天。請確認後儲存。」

**理由**：避免「打開 modal 自動觸發 PUT」的副作用；明確告知使用者狀態變更，由使用者決定何時生效。

**Alternatives considered**：Migration 階段批次 `UPDATE show_schedules SET frequency='daily' WHERE frequency='hourly'` — 拒絕，使用者要求僅 fallback。但若使用者後續希望清掉，可獨立 change 處理。

### Day picker UI：segmented button vs select

**選擇**：Segmented button — 七個方塊 `[一][二][三][四][五][六][日]`，單選；選中 background `TOKEN.accent` 文字白色，未選 background `TOKEN.surfaceRaised` 文字 `TOKEN.textSecondary`。寬度不夠時自動 wrap。

**理由**：星期是「一次決定」型設定，明確 > 緊湊；七選項全部可見一次點選完成。配色沿用既有 TOKEN。

**Alternatives considered**：`<select>` dropdown — 多一次點擊、看不到全貌；checkbox 多選 — 超出本次範圍（單一觸發日就夠）。

### 動態提示文案組字

**選擇**：在「執行時間」input 下以 `TOKEN.textMuted` 12px 顯示一行：

| frequency | 文案（zh） | 文案（en） |
|---|---|---|
| daily | `每日 {run_time} (UTC) 觸發` | `Runs daily at {run_time} (UTC)` |
| weekly | `每週{day_zh} {run_time} (UTC) 觸發` | `Runs every {day_en} at {run_time} (UTC)` |
| manual | `不會自動執行` | `Will not run automatically` |

`day_zh` 對照表：0=一, 1=二, 2=三, 3=四, 4=五, 5=六, 6=日。

**理由**：避免使用者僅從 frequency + run_time 兩個欄位無法快速確認最終效果。

## Risks / Trade-offs

- **[Risk] 既有 hourly row 在 fallback 顯示 daily，但 DB 仍是 hourly，cron 永遠不會觸發** → 使用者下次編輯儲存即修正；同時編輯 modal 顯示警示文案讓使用者知道需要重新儲存。中期可考慮獨立 migration 一次清空。
- **[Risk] 三分頁切換後，使用者可能誤以為其他分頁的列「消失」** → tab 標籤後加計數 badge（例：`已完成 (12)`）讓總量可見。
- **[Risk] day_of_week migration 對運行中環境若有殘留 hourly row，未來想 backfill 到 weekly 的某天時無從推斷** → 不在本次處理；hourly 僅 fallback 到 daily（不需 day_of_week），無此問題。
- **[Trade-off] 子分頁狀態用 local state 不持久化** → 重新整理回到 `active` 分頁；可接受，後台操作非高頻深連結場景。
- **[Trade-off] 三分頁仍共用同一個 5 秒輪詢** → 切到「已完成」分頁時也會 refetch pending/running 資料；無顯著成本（同一 endpoint），保持邏輯簡單。

## Migration Plan

1. Alembic migration 新增 `day_of_week INTEGER NOT NULL DEFAULT 0` 至 `show_schedules` 表；既有列自動 backfill 為 0（週一），與舊行為一致。
2. 後端模型、schema、cron tick 改動可與 migration 同 PR 部署 — 部署順序：DB migration → backend → frontend，三者獨立可漸進式。
3. 部署後使用者打開既有 `frequency='hourly'` 的排程編輯 modal 時：select 顯示 `每天`、警示文案出現；使用者按儲存後 DB 才更新成 `daily`。
4. **Rollback**：移除 `day_of_week` 欄位需 down migration（drop column），會丟失使用者已配置的星期資訊；建議部署後若需 rollback，先請使用者匯出 `day_of_week` 設定再 drop。前端 + cron_tick rollback 可直接 revert commit。
