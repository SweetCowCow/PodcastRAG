## Context

後台 ScheduleTab 目前以硬寫的 mock 陣列渲染節目排程清單，所有動作（新增、切換啟用、同步）只改本地 React state。現有後端已有 `POST /shows/{show_id}/transcribe-all`（批次觸發轉錄）和 `rss_parser` 服務（解析 RSS feed），但缺少排程設定的持久化機制。

## Goals / Non-Goals

**Goals:**

- `show_schedules` 資料表：每個節目最多一筆排程設定（1:1 與 `shows`）
- 後端 CRUD：`GET/PUT/DELETE /shows/{show_id}/schedule`
- Admin 列表：`GET /admin/schedules` 回傳所有節目的排程設定 + pending 集數 + 最後轉錄時間
- RSS 預覽：`GET /rss-preview?url=<rss_url>` 呼叫既有 `fetch_and_parse`，回傳名稱、集數數量、最新發佈日期
- 前端 ScheduleTab 串接上述 API，取代所有 mock 資料與 setTimeout

**Non-Goals:**

- 不實作真正的自動排程執行（Celery Beat / APScheduler）；`nextRun` 為純計算值
- 不記錄排程執行歷史
- 不實作 progress 百分比（running 狀態直接由 transcript.status 判斷）

## Decisions

### show_schedules 資料表設計

`show_schedules` 以 `show_id` 為唯一 FK（ON DELETE CASCADE），欄位包含：

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | UUID PK | |
| `show_id` | UUID FK unique | |
| `enabled` | Boolean | 預設 false |
| `frequency` | Enum(daily/weekly/manual) | |
| `run_time` | String(5) | HH:MM 格式 |
| `whisper_model` | String(50) | 如 `large-v3`、`medium` |
| `max_episodes` | Integer | 0 = 無限制 |
| `created_at` | DateTime | |
| `updated_at` | DateTime | auto-update |

**理由**：1:1 relation 而非直接欄位加在 `shows` 表，是為了讓排程設定為可選（節目可存在但無排程），且邏輯清楚分離。

### GET /admin/schedules 聚合查詢

回傳每個節目的排程設定 + 動態計算的 `pending_count`（LEFT JOIN episodes → transcripts，status != 'completed' 或無 transcript row）+ `last_transcribed_at`（`transcripts` 表中該節目最新的 `updated_at`）。

**理由**：避免為每個節目個別發 N 個請求，一次聚合所有狀態減少前端 loading 複雜度。

### RSS Preview 端點

`GET /rss-preview?url=<encoded_url>` 呼叫既有 `fetch_and_parse(url)` 並只回傳 `{ title, episode_count, latest_published_at }`，不建立 show 資料。

**理由**：直接重用已有的 RSS parser 邏輯，不重複實作。

### 前端 ScheduleTab 改寫策略

掛載時 fetch `GET /admin/schedules`，每個節目卡片的 enable/disable toggle 呼叫 `PUT /shows/{id}/schedule`（`enabled` 欄位），「同步所有」按鈕 for-each 呼叫 `POST /shows/{id}/transcribe-all`（串行或 Promise.all）。

**理由**：複用已有的 transcribe-all endpoint，不需要新的批次 API。

## Risks / Trade-offs

- `GET /admin/schedules` 包含聚合 SQL 查詢，show 數量大時可能較慢 → 目前規模不需索引最佳化，接受此 trade-off
- RSS preview 端點直接呼叫外部 RSS URL，可能因網路逾時導致請求掛起 → 設定 5 秒 timeout，逾時回 HTTP 504

## Migration Plan

1. 新增 Alembic migration 建立 `show_schedules` 表
2. `docker compose exec backend alembic upgrade head`
3. 無需資料回填（排程設定為可選）
4. 前端直接切換為新 API，無需相容舊 mock 格式
