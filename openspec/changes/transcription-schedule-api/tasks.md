## 1. 資料庫：show_schedules 資料表

- [x] 1.1 實作 Requirement: Show schedule settings persisted per show（show_schedules 資料表設計）——在 `backend/app/models/show_schedule.py` 建立 `ShowSchedule` SQLAlchemy model：UUID PK `id`、UUID FK `show_id`（unique，ON DELETE CASCADE）、`Boolean enabled`（預設 False）、`String(10) frequency`（`daily`/`weekly`/`manual`）、`String(5) run_time`（HH:MM）、`String(50) whisper_model`、`Integer max_episodes`（0=無限制）、`DateTime created_at`（server_default=func.now()）、`DateTime updated_at`（onupdate=func.now()）；在 `backend/app/models/__init__.py` 匯入 `ShowSchedule`
- [x] 1.2 在 `backend/alembic/versions/` 新增 migration 檔（命名如 `d2e3f4a5b6c7_add_show_schedules.py`）：`op.create_table('show_schedules', ...)` 包含所有欄位定義；`op.create_foreign_key` 對 `shows.id` 加 `ondelete='CASCADE'`；`op.create_unique_constraint` 確保 `show_id` 唯一

## 2. 後端：排程 CRUD API

- [x] 2.1 在 `backend/app/schemas/schedule.py` 建立 Pydantic schemas：`ScheduleUpsert`（PUT body：`enabled`、`frequency`、`run_time`、`whisper_model`、`max_episodes`，所有欄位為 Optional）；`ScheduleResponse`（回傳：以上所有欄位 + `show_id`、`created_at`、`updated_at`）
- [x] 2.2 建立 `backend/app/api/schedules.py`，實作 `GET /shows/{show_id}/schedule`：查詢 `show_schedules.show_id == show_id`；若無資料回 404；否則回 200 + `ScheduleResponse`
- [x] 2.3 在 `backend/app/api/schedules.py` 實作 `PUT /shows/{show_id}/schedule`（Show schedule settings persisted per show）：若無 schedule 則 INSERT，若已存在則 UPDATE 所有提供欄位並更新 `updated_at`；回 200 + `ScheduleResponse`
- [x] 2.4 在 `backend/app/api/schedules.py` 實作 `DELETE /shows/{show_id}/schedule`：刪除對應 row，回 204；row 不存在回 404
- [x] 2.5 在 `backend/app/main.py` 匯入並掛載 `schedules.router`（prefix 沿用 `/shows`）

## 3. 後端：Admin schedules 列表端點

- [x] 3.1 實作 Requirement: Admin schedules list endpoint（GET /admin/schedules 聚合查詢）——在 `backend/app/api/schedules.py` 新增 `GET /admin/schedules`：以 LEFT JOIN 連接 `shows → show_schedules`，並以子查詢計算每個 show 的 `pending_count`（episodes 中無 `status='completed'` transcript 的集數）與 `last_transcribed_at`（該 show 最新 completed transcript 的 `updated_at`）；回傳 list of `AdminScheduleItem`（`show_id`、`show_title`、`rss_url`、`schedule: ScheduleResponse | None`、`pending_count: int`、`last_transcribed_at: datetime | None`）
- [x] 3.2 在 `backend/app/schemas/schedule.py` 新增 `AdminScheduleItem` Pydantic schema（對應 3.1 回傳格式）；在 `backend/app/main.py` 的 schedules router 確認 `/admin/schedules` route 已包含在掛載路徑下

## 4. 後端：RSS preview 端點

- [x] 4.1 實作 Requirement: RSS preview endpoint——在 `backend/app/api/shows.py` 新增 `GET /rss-preview` 端點（query param `url: str`）：呼叫既有 `fetch_and_parse(url)` 並設定 5 秒 HTTP timeout；成功時回 200 + `{ title, episode_count, latest_published_at }`；`RssParseError` 或解析失敗回 422；timeout（`asyncio.TimeoutError` 或 `httpx.TimeoutException`）回 504
- [x] 4.2 在 `backend/app/schemas/show.py` 新增 `RssPreviewResponse` Pydantic schema：`title: str`、`episode_count: int`、`latest_published_at: str | None`

## 5. 前端：ScheduleTab 串接真實 API

- [x] 5.1 實作 Requirement: ScheduleTab frontend fetches real data（前端 ScheduleTab 改寫策略）——在 `src/AdminPage.jsx` 的 `ScheduleTab` 元件：移除 `React.useState` 中的硬寫 mock shows 陣列；改為 `const [shows, setShows] = React.useState(null)` + `const [loading, setLoading] = React.useState(true)` + `const [fetchError, setFetchError] = React.useState(null)`；在 `React.useEffect` 中 fetch `${API_BASE}/admin/schedules`，成功設 `setShows(data)`，失敗設 `setFetchError(err.message)`
- [x] 5.2 修改 `ScheduleTab` 渲染邏輯：`loading` 時顯示 spinner；`fetchError` 時顯示錯誤訊息；`shows` 有值時渲染 `shows.map(item => <ScheduleCard .../>)`，每張卡片使用 `item.show_title`、`item.schedule`（nullable）、`item.pending_count`、`item.last_transcribed_at`
- [x] 5.3 修改 enable/disable toggle：點擊時呼叫 `PUT ${API_BASE}/shows/${item.show_id}/schedule` 帶 `{ enabled: !current }` body；成功後更新本地 shows state 中對應 item 的 `schedule.enabled`
- [x] 5.4 修改「同步所有」按鈕（Sync All）：點擊時對所有 `item.schedule?.enabled === true` 的 show 呼叫 `POST ${API_BASE}/shows/${item.show_id}/transcribe-all`（使用 `Promise.all`）；完成後以 toast/alert 顯示「已排入 N 個節目的轉錄任務」

## 6. 前端：RSS preview 串接

- [x] 6.1 實作 Requirement: RSS preview endpoint（前端部分）——修改 `ScheduleTab` 的 `handleFetchRSS`：移除 `setTimeout` mock；改為 fetch `${API_BASE}/rss-preview?url=${encodeURIComponent(form.rss)}`；成功時以回傳的 `title`、`episode_count` 更新 `rssPreview` state；失敗時顯示錯誤訊息於表單下方

## 7. 驗證

- [x] 7.1 執行 `docker compose exec backend alembic upgrade head`，確認 `show_schedules` 資料表建立成功（`\d show_schedules`）
- [x] 7.2 `curl -X PUT http://localhost:8000/shows/{show_id}/schedule -H 'Content-Type: application/json' -d '{"enabled":true,"frequency":"daily","run_time":"06:00","whisper_model":"large-v3","max_episodes":0}'`，確認回 200 + schedule JSON
- [x] 7.3 `curl http://localhost:8000/admin/schedules | python3 -m json.tool`，確認回傳每個節目含 `pending_count` 與 `last_transcribed_at`
- [x] 7.4 `curl 'http://localhost:8000/rss-preview?url=<valid_rss_url>'`，確認回傳 `title`、`episode_count`
- [x] 7.5 瀏覽器開啟後台 → 轉錄排程管理：確認載入真實節目清單（非 mock）；toggle 啟用後重新整理仍保持狀態；RSS 預覽欄位顯示真實節目名稱
