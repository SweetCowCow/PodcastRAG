## Context

PodcastRAG 的後台目前對以下兩類資訊沒有可見度：

1. **節目整體轉錄進度**：使用者必須逐集點開才能知道進度，更別說失敗原因要 SQL 才看得到
2. **外部 API 健康狀態**：2026-04-24 的 OOM 修復部署後首次觸發轉錄，OpenAI 回 429 insufficient_quota，錯誤被正確分類為 failed 寫入 DB，但後台無法一眼看到「是我程式爆了還是 OpenAI 沒額度了」

同時存在一個 schema 補洞：`transcripts` 沒 `updated_at` 欄位，先前 `transcription-schedule-api` change 的 spec 原要求用它計算 `last_transcribed_at`，當時以 `transcribed_at` 替代屬於 workaround。

本 change 的顯示資料有部份（queue_depth、retry_count）需要 B2 `concurrency-control-and-retry` 提供的資料源。但本 change 必須能獨立部署，不等 B2；B2 尚未上時對應欄位回 null、前端隱藏。

## Goals / Non-Goals

**Goals:**

- 後端提供兩個聚合 endpoint：`GET /shows/{id}/transcription-status`、`GET /admin/external-api-status`
- 引入輕量 api_health tracker：所有外部 API（OpenAI Whisper、Chat、Embedding）呼叫點統一呼叫，記錄時間 / 成功失敗 / 錯誤分類
- 錯誤分類統一在後端完成，前端只消費分類結果（不解析 raw error message）
- 補齊 `transcripts.updated_at` 欄位並以 SQLAlchemy `onupdate` 自動更新
- 前端顯示：ScheduleTab 節目卡片可展開顯示進度，AdminPage 新 tab 顯示 API 狀態
- Polling：ScheduleTab 5s、AdminPage 15s；可單純 setInterval，不用 SSE/WS

**Non-Goals:**

- Token 額度 / cost 計算（需 OpenAI usage API，延後到獨立 change）
- SSE / WebSocket（polling 已足夠，部署更簡單）
- Prometheus / Grafana 整合
- 獨立使用量統計 Dashboard（另列技術債）
- Celery retry 或並發控制（B2 負責）
- 動態調整 polling 頻率或背景 tab 停止 polling（先做簡單版）

## Decisions

### api-health tracker 儲存方案選 Redis hash

- **決定**：用 Redis 儲存最近 N=20 筆每個 API 的 call metadata，用 key 格式 `api_health:{api_name}` 存 list + LTRIM 維持長度
- **替代方案 1（SQL table）**：獨立 `api_health_events` 表 — 被否決，原因是此資料不需持久化（只需「最近狀態」即可）、新 table 牽動 migration 與 polling 的 SQL 成本
- **替代方案 2（in-memory）**：worker 重啟會丟，且 backend 與 worker 共享資料困難 — 被否決
- **Key schema**：
  - `api_health:openai_whisper` → Redis LIST（最近 20 筆 JSON，LPUSH + LTRIM 0 19）
  - `api_health:openai_chat` → 同上
  - `api_health:openai_embedding` → 同上
- **每筆 payload**：`{ts: epoch_ms, ok: bool, duration_ms: int, error_category: str|null, http_status: int|null}`
- **TTL**：整個 key 設 TTL 7 天，避免長期不用仍佔用

### 錯誤分類器 vs 直接暴露 HTTP status

- **決定**：後端做分類，前端只拿分類結果（enum）
- **分類邏輯**（在一個共用 `api_health.classify_error(exc) -> str`）：
  - `openai.RateLimitError` 且 code `insufficient_quota` → `quota_exceeded`
  - `openai.RateLimitError`（其他）→ `rate_limited`
  - `openai.AuthenticationError` → `auth_error`
  - `openai.APIStatusError` 5xx → `server_error`
  - `httpx.TimeoutException`、`httpx.ConnectError`、`asyncio.TimeoutError` → `network_error`
  - 其他 → `unknown`
- **理由**：前端不用寫 parser，後端更新分類邏輯不用動前端；未來增加新 provider 只要擴 classify_error

### transcription-status endpoint 實作策略

- **決定**：單次聚合 SQL 查詢，SELECT status, COUNT(*) GROUP BY status，外加兩個子查詢取 currently_processing 與 recent_failures
- **不做快取**：polling 5s 週期 + SQL 聚合在幾百集 episodes 規模夠快（<50ms）；加快取反增複雜度
- **依 show_id 過濾**：在 transcripts join episodes where episode.show_id = ? — 需確保 `transcripts.episode_id` 有 index（現有 schema 應有 foreign key index）

### updated_at 自動更新策略

- **決定**：SQLAlchemy Column level `onupdate=func.now()`，不走 DB trigger
- **理由**：trigger 需跨 migration 管理且 DB-specific；ORM level 夠用
- **遷移時對既有 row**：migration 用 `server_default=func.now()` 填入現有 row 的 `updated_at`，後續 ORM 更新時才走 `onupdate`

### 前端 polling 策略

- **決定**：ScheduleTab 每 5s polling `transcription-status`（每個展開的節目卡片各自 polling），AdminPage 外部 API tab 每 15s polling
- **停止條件**：元件 unmount 時 clearInterval；切換 tab 時停 polling
- **不做**：背景頁面 throttle、指數退避、階段性 polling — 先簡單版，實務發現問題再加

### 前後端耦合設計：避免 B2 阻塞

- **決定**：`transcription-status` 回應 schema 本版本**不**回 `queue_depth` / `retry_count`；留給 B2 在 archive 時加入 `MODIFIED` delta。前端目前不 render 這兩欄。
- **理由**：本 change 與 B2 獨立，不等；未來 B2 加欄位，前端接收但當 null 即隱藏

## Risks / Trade-offs

- **[Redis 失聯導致 tracker 寫入 fail]** → tracker 呼叫放 try/except 裡記 warning log，**不**阻斷實際 API 呼叫；GET /admin/external-api-status 在 Redis 不通時回 empty list + 標記降級
- **[每個節目卡片獨立 polling 造成 N 個 request/5s]** → 規模假設：同時展開節目數 ≤ 3，request 量 ≤ 0.6 req/s，可接受；若未來節目超多可重構為單一 global endpoint
- **[error_message 可能含敏感資訊]** → 現階段後台只給 admin 看，可接受；truncate 至 200 字降低意外洩漏的資料量
- **[updated_at migration 對既有資料]** → `server_default=func.now()` 會把所有舊 row 的 `updated_at` 設為 migration 執行時間，**不代表**真正最後更新時間；這是一次性情況，標記於 migration docstring
- **[polling 壓力]** → 若規模超出假設再考慮加 Redis 快取層或引入 SSE

## Migration Plan

1. 部署含 migration 的 backend 版本 → alembic 自動 apply → 新欄位 `transcripts.updated_at` 就位
2. api_health tracker 在第一次 OpenAI 呼叫時自動寫 Redis，無需 bootstrap
3. 前端新 UI 由使用者開啟 AdminPage「外部 API 狀態」tab 或展開 ScheduleTab 卡片即自動觸發 polling
4. 回滾：alembic downgrade 移除 `updated_at`；前端舊版本會忽略新欄位；api_health Redis key 可任意清除無副作用

## Open Questions

(none — 所有選項均有決定)
