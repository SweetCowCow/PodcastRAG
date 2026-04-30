## 1. Backend：show schedule settings persisted per show（加 day_of_week 欄位）

> Spec：`transcription-schedule` → `Show schedule settings persisted per show`
> Design：`Weekday 欄位編號`

- [x] 1.1 在 `backend/app/models/show_schedule.py` 的 `ShowSchedule` model 新增 `day_of_week: Mapped[int]`，型別 `Integer`，`nullable=False`，`default=0`，`server_default="0"`（Python `datetime.weekday()` 慣例：0=週一 … 6=週日）
- [x] 1.2 建立 Alembic migration 檔案 `backend/alembic/versions/<timestamp>_add_day_of_week_to_show_schedules.py`：upgrade 加 `day_of_week INTEGER NOT NULL DEFAULT 0`，downgrade drop column
- [x] 1.3 在 `backend/app/schemas/schedule.py` 的 `ScheduleUpsert` 與 `ScheduleResponse` 加 `day_of_week` 欄位，加 Pydantic 驗證 `Field(ge=0, le=6)`，`ScheduleUpsert` 中型別為 `int | None = None`（沿用其他 optional field 慣例）
- [x] 1.4 更新 `backend/app/api/schedules.py` 的 `SCHEDULE_DEFAULTS` dict 加 `"day_of_week": 0`
- [ ] 1.5 在本機執行 `alembic upgrade head` 驗證 migration 成功；用 `psql` 確認既有列 `day_of_week=0`
- [x] 1.6 對齊 spec requirement「Show schedule settings persisted per show」— 確認本群所有任務涵蓋該 requirement 全部 scenarios（含 day_of_week 欄位、422 驗證、CASCADE、migration backfill）

## 2. Backend：cron tick triggers refresh and enqueue per schedule（weekly 改讀 day_of_week）

> Spec：`transcription-schedule` → `Cron tick triggers refresh and enqueue per schedule`

- [x] 2.1 修改 `backend/app/workers/cron_tick.py` 的 `_is_due` 函式：`if schedule.frequency == "weekly":` 分支從 `return weekday == 0` 改為 `return weekday == schedule.day_of_week`
- [x] 2.2 更新 `_is_due` 的 docstring 說明 weekly 現在讀 `day_of_week`，引用 design 的 weekly due-evaluation 表
- [x] 2.3 在 `backend/tests/` 寫單元測試覆蓋：daily 命中 / weekly 命中正確日 / weekly 不命中其他日 / manual 永遠不命中。測試資料按 design.md 中的 weekly due-evaluation 表
- [x] 2.4 對齊 spec requirement「Cron tick triggers refresh and enqueue per schedule」— 確認 `_is_due` weekly 分支符合 spec 規定的三段判斷（daily 每日命中、weekly 比對 day_of_week、manual 永不命中）

## 3. Frontend：admin page exposes a Transcription Queue tab（佇列三 sub-tab 切版）

> Spec：`admin-transcription-queue-ui` → `Admin page exposes a Transcription Queue tab`
> Design：`Frontend 切分頁 vs 後端分頁`、`Sub-tab 切換用本地 state 而非 URL route`、`子分頁命名`、`子分頁內 section 是否保留小標題`

- [x] 3.1 在 `src/QueueTab.jsx` 的 `QueueTab` 元件 useState 新增 `const [activeTab, setActiveTab] = React.useState('active')`，三個合法值 `'active' | 'completed' | 'closed'`（local state，不註冊新 page route）
- [x] 3.2 在 `Section` 列表上方加入 sub-tab 切換列：三顆按鈕 `[進行中 (N)] [已完成 (N)] [已結束 (N)]`，計數 N 為對應 status 桶的 length 加總（active=pending+running, completed=completed, closed=failed+cancelled）。選中按鈕底線 `TOKEN.accent`，未選中文字 `TOKEN.textSecondary`
- [x] 3.3 把現有五個 `<Section>` 改為條件式渲染：`activeTab === 'active'` 顯示 pending + running 兩個 Section（保留現有 section title 與拖曳邏輯）；`activeTab === 'completed'` 顯示單一 completed flat 列表（無 section header）；`activeTab === 'closed'` 顯示 failed + cancelled 兩個 Section
- [x] 3.4 確認 `pendingDisplay` / `pendingOverride` 拖曳邏輯只在 `active` 分頁可見時運作（拖曳的 `draggable` 與 drop handler 已綁在 pending Section 內，自然只在 active tab 渲染時生效）
- [x] 3.5 polling 邏輯維持不變（5 秒輪詢同一 endpoint），切 sub-tab 不觸發額外 API 呼叫
- [x] 3.6 Empty state：`closed` sub-tab 兩個 section 都空時，各自顯示「空」/ "Empty"；count badge 顯示 0
- [x] 3.7 雙語標籤檢查：`zh` lang `進行中 / 已完成 / 已結束`，`en` lang `Active / Completed / Closed`
- [x] 3.8 對齊 spec requirement「Admin page exposes a Transcription Queue tab」— 走過全部 scenarios（三 sub-tab 渲染、active/closed/completed 各自分組、切 sub-tab 不送 request、empty placeholder、polling 5 秒）

## 4. Frontend：schedule modal frequency selector excludes hourly and falls back gracefully

> Spec：`admin-show-management-ui` → `Schedule modal frequency selector excludes hourly and falls back gracefully`
> Design：`既有 hourly row 處理：前端 fallback、不寫回`

- [x] 4.1 在 `src/AdminPage.jsx` 兩處 frequency `<select>`（搜 `value="hourly"`，目前在 line ~842 與 ~1091）刪掉 `<option value="hourly">` 整行
- [x] 4.2 在 `editState` 初始化邏輯（搜 `frequency: 'manual'` 與 `frequency: item.schedule.frequency`）加入 fallback：若 `item.schedule.frequency` 不在 `['daily','weekly','manual']` 內，初始化為 `'daily'`，並在 component state 設一個 flag `hourlyFallback: true` 以驅動警示文案顯示
- [x] 4.3 在 frequency `<select>` 下方依 `editState.form.frequency` 渲染：`hourlyFallback` 為 true 時顯示警示「原設定『每小時』已停用，已改為每天，請確認後儲存。」/ "The previous 'hourly' setting is no longer supported; switched to daily. Please confirm and save."（`TOKEN.warning` color，12px）
- [x] 4.4 確認儲存時 PUT body 包含 `frequency='daily'`，DB 才會被更新；不在 modal 開啟瞬間自動 PUT
- [x] 4.5 對齊 spec requirement「Schedule modal frequency selector excludes hourly and falls back gracefully」— 三選項顯示、hourly fallback 顯示警示、儲存後 DB 寫回 daily 三個 scenarios 全測過

## 5. Frontend：schedule modal renders day_of_week selector for weekly frequency

> Spec：`admin-show-management-ui` → `Schedule modal renders day_of_week selector for weekly frequency`
> Design：`Day picker UI：segmented button vs select`

- [x] 5.1 在 modal 的「執行時間」與「Whisper 模型」之間插入新 day_of_week segmented button group：條件 `editState.form.frequency === 'weekly'` 時渲染。七顆按鈕橫排（flex wrap），label 中文 `[一][二][三][四][五][六][日]`、英文 `[Mon][Tue][Wed][Thu][Fri][Sat][Sun]`
- [x] 5.2 按鈕綁 `editState.form.day_of_week`（0–6），onClick 時 `setEditState(s => ({...s, form: {...s.form, day_of_week: i}}))`。選中 background `TOKEN.accent` 文字 `#fff`；未選 background `TOKEN.surfaceRaised` 文字 `TOKEN.textSecondary`
- [x] 5.3 form 預設值：搜尋 form 初始化處（line ~414, ~500）補上 `day_of_week: 0`；既有 schedule 編輯時讀 `item.schedule.day_of_week ?? 0`
- [x] 5.4 PUT 送出 body（line ~673 `frequency: form.freq` 那塊與 modal 儲存路徑）加上 `day_of_week: form.day_of_week`
- [x] 5.5 schedule 摘要顯示處（line ~977）若 frequency 為 weekly 額外顯示星期幾（例：`頻率: weekly · 三 09:30`）
- [x] 5.6 對齊 spec requirement「Schedule modal renders day_of_week selector for weekly frequency」— 條件式渲染、預設值、PUT 帶 day_of_week、切 frequency 後保留值四個 scenarios 全測過

## 6. Frontend：schedule modal hides run_time and day_of_week for manual frequency

> Spec：`admin-show-management-ui` → `Schedule modal hides run_time and day_of_week for manual frequency`

- [x] 6.1 「執行時間」`<input type="time">`（line ~1099）外面加 `editState.form.frequency !== 'manual' && (...)` 條件，manual 時不渲染
- [x] 6.2 day_of_week segmented group 條件已限制為 `frequency === 'weekly'`，故 manual 時自然不渲染（與第 5.1 條件配合，不需額外修改）
- [x] 6.3 確認 Whisper 模型選擇器與「每次最多轉錄集數」input 在 manual 模式下仍可見
- [x] 6.4 form 送 PUT 時 `manual` 模式仍帶 `run_time`（沿用 form state 預設 `06:00`）與 `day_of_week`（預設 0），讓後端 row 保持完整
- [x] 6.5 對齊 spec requirement「Schedule modal hides run_time and day_of_week for manual frequency」— 隱藏執行時間與星期、保留 model 與 max_episodes、PUT 仍帶 placeholder 三個 scenarios 全測過

## 7. Frontend：schedule modal shows dynamic next-run hint

> Spec：`admin-show-management-ui` → `Schedule modal shows dynamic next-run hint`
> Design：`動態提示文案組字`

- [x] 7.1 在 `src/AdminPage.jsx` modal 內新增 helper function `formatScheduleHint(form, lang)` 接收 `{frequency, run_time, day_of_week}` 與 lang，回傳對應文案（zh/en），規則：
  - daily → `每日 {run_time} (UTC) 觸發` / `Runs daily at {run_time} (UTC)`
  - weekly → `每週{day_zh} {run_time} (UTC) 觸發` / `Runs every {day_en} at {run_time} (UTC)`
  - manual → `不會自動執行` / `Will not run automatically`
- [x] 7.2 day_zh 對照：0=一 1=二 2=三 3=四 4=五 5=六 6=日；day_en 對照：Mon/Tue/Wed/Thu/Fri/Sat/Sun
- [x] 7.3 在「執行時間」input 下方（manual 時則改為在 frequency select 下方）渲染 `<div style={{color: TOKEN.textMuted, fontSize: 12}}>{formatScheduleHint(editState.form, lang)}</div>`
- [x] 7.4 hint 隨著 frequency / run_time / day_of_week 變更即時 re-render（無需額外 effect，依賴 state 即可）
- [x] 7.5 對齊 spec requirement「Schedule modal shows dynamic next-run hint」— daily / weekly / manual / 切換即時更新四個 scenarios 全測過

## 8. 整合測試與部署驗證

- [ ] 8.1 本機 `docker compose up` 啟動全棧；用 `psql` 確認 migration 跑完後 `\d show_schedules` 看到 `day_of_week` 欄位
- [ ] 8.2 在後台手動測試：建立新排程選 `每天` → 看到 daily hint；切 `每週` → 看到 segmented day picker、選星期三、看到 `每週三 ... 觸發` hint；切 `手動` → 執行時間與星期消失、看到「不會自動執行」hint
- [ ] 8.3 用 `psql` 寫一筆 `frequency='hourly'` 的 row，重新整理打開 modal：select 顯示 `每天`、警示文案出現；按儲存後 DB row 變成 `frequency='daily'`
- [ ] 8.4 在後台轉錄序列分頁：用 `psql` 注入或自然累積 5 種 status 各幾筆，逐一切 sub-tab 確認分組正確、count badge 對；拖曳測試在 `active` 分頁仍可動；強制取消、重試、忽略按鈕在對應 sub-tab 內仍可動
- [ ] 8.5 push 到 Zeabur prod 並用 chrome-devtools-mcp 跑一次完整驗證流程（依使用者偏好）：登入後台 → 排程 modal 三種頻率切換 → 佇列三 sub-tab 切換 → 至少跑一次批次轉錄到完成
