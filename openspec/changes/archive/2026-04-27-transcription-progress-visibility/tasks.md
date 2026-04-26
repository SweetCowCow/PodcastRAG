## 1. DB schema migration

- [x] 1.1 在 `backend/app/models/transcript.py` 的 `Transcript` model（對應 Requirement: transcripts table）依 Decision "updated_at 自動更新策略" 新增 `updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())`，import `func` from `sqlalchemy.sql`
- [x] 1.2 實作 Requirement: Alembic migration for transcripts.updated_at — 執行 `alembic revision --autogenerate -m "add transcripts.updated_at"` 後手動檢查 migration 檔內容含 `op.add_column('transcripts', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))` 與對稱 downgrade 的 `op.drop_column`
- [x] 1.3 本機 `alembic upgrade head` 再 `alembic downgrade -1` 再 `alembic upgrade head` 驗證 upgrade / downgrade / re-upgrade 皆成功，DB 中 transcripts 有 updated_at 欄位

## 2. api_health tracker service

- [x] 2.1 建 `backend/app/services/api_health.py`，實作 Requirement: External API health tracker service 的常數 `API_NAMES = ("openai_whisper", "openai_chat", "openai_embedding")`、`MAX_EVENTS = 20`、`TTL_SECONDS = 604800`
- [x] 2.2 實作 Requirement: Error classifier produces a stable enumerated category（依 Decision "錯誤分類器 vs 直接暴露 HTTP status" 在後端做分類）：`classify_error(exc, http_status) -> Literal["quota_exceeded", "rate_limited", "auth_error", "server_error", "network_error", "unknown"]`，優先序：quota_exceeded（RateLimitError + insufficient_quota code）→ rate_limited（其他 RateLimitError）→ auth_error（AuthenticationError 或 401/403）→ server_error（5xx）→ network_error（httpx.Timeout/ConnectError, asyncio.TimeoutError, APIConnectionError）→ unknown
- [x] 2.3 依 Decision "api-health tracker 儲存方案選 Redis hash" 實作 `record(api_name, ok, duration_ms, error_category=None, http_status=None)`：用 `redis.Redis` client 以 `LPUSH` + `LTRIM 0 19` + 首次寫入時 `EXPIRE` 7 天；整個函式包 try/except 捕捉 `redis.RedisError` 後只 `logger.warning(...)` 不 re-raise
- [x] 2.4 實作 `get_recent(api_name, limit=20) -> tuple[list[dict], bool]` 回傳 `(events, degraded)`：成功時 `LRANGE 0 limit-1` 解析 JSON，失敗時回 `([], True)`
- [x] 2.5 寫最小 unit test `backend/tests/test_api_health.py` 涵蓋 classify_error 的六個 scenario，每個對應一個 assert（用 `openai.RateLimitError`、`AuthenticationError` 等實際 exception class 建構 mock）

## 3. 整合 api_health tracker 到外部 API 呼叫點

- [x] 3.1 實作 Requirement: OpenAI provider records api-health events — 在 `backend/app/services/transcription/openai_provider.py` 的 `_transcribe_sync` 單一請求路徑：在 `self._client.audio.transcriptions.create` 前後記錄 `time.monotonic_ns()`，成功時呼叫 `api_health.record("openai_whisper", ok=True, duration_ms=..., http_status=200)`；失敗時 `except Exception as exc:` 先 call `api_health.record("openai_whisper", ok=False, ..., error_category=classify_error(exc, ...))` 再 `raise`
- [x] 3.2 在 `_transcribe_sync` 的 chunk 迴圈同樣包 try/except 記錄每個 chunk 的 record 事件；失敗拋出時停止迴圈（spec Scenario "Chunked path emits one event per chunk" 要求 chunk 2 失敗後 chunk 3 不發送）
- [x] 3.3 在 `backend/app/services/embedding.py`（embed_texts 呼叫 OpenAI embedding 的位置）包同樣 pattern 記 `openai_embedding` 事件
- [x] 3.4 找到 LLM answer / rewrite 的實際呼叫點（搜 `grep -rn "chat.completions.create\|answer_api_key\|rewrite_api_key" backend/app/`），在該處包 `openai_chat` 事件；若尚未整合 LLM client 成獨立檔，就在 rag_query 或相關 service 就地加 tracker（不新增 abstraction）
- [x] 3.5 每個整合點都驗證「tracker raise 不影響呼叫端」：手動 monkeypatch `api_health.record` 讓它 raise，確認 openai 實際 call 路徑仍 return 正常結果

## 4. 後端 API endpoints

- [x] 4.1 在 `backend/app/schemas/transcription_status.py` 定義 Pydantic schemas：`TranscriptionStatusCounts`, `CurrentlyProcessingItem`, `RecentFailureItem`, `TranscriptionStatusResponse`
- [x] 4.2 實作 Requirement: Transcription progress aggregate endpoint per show，依 Decision "transcription-status endpoint 實作策略" 與 Decision "前後端耦合設計：避免 B2 阻塞" —— 在 `backend/app/api/shows.py` 新增 `GET /shows/{show_id}/transcription-status` endpoint：先 `db.get(Show, show_id)`（404 if null），再用單一 SELECT 做 `status, COUNT(*) GROUP BY status`，再兩個獨立 query 取 currently_processing 與 recent_failures（各 limit 10）；error_message 用 Python `[:200]` 切片；回應 schema 本版本不包含 queue_depth / retry_count 欄位（留給 B2 日後 MODIFIED 加入）
- [x] 4.3 在 `backend/app/schemas/api_health.py` 定義 `ApiHealthEvent`, `ApiEntry`, `ExternalApiStatusResponse`
- [x] 4.4 實作 Requirement: External API status endpoint for admin —— 在 `backend/app/api/admin.py` 新增 `GET /admin/external-api-status`：對三個 api_name 逐一呼叫 `api_health.get_recent(name, 20)` 組裝回傳；即使 Redis 掛了每個 entry 仍 return `latest=null, recent=[], degraded=True`
- [x] 4.5 使用 httpx 或 FastAPI TestClient 寫 integration test：(a) 空 show 回 counts 全零、(b) 含 processing+failed 混合資料時回對應 counts 與 list、(c) 未知 show_id 回 404、(d) /admin/external-api-status 在 Redis 不通時回 degraded=True

## 5. 前端 ScheduleTab 進度 panel

- [x] 5.1 在 `src/Shared.jsx` 沿用 `Badge` 的變體供 `error_category` 使用（success/danger/warning/muted 已有），並新增 `<ProgressCounts>` 小元件顯示 pending/processing/completed/failed 四欄位
- [x] 5.2 實作 Requirement: Schedule card exposes expandable transcription progress panel —— 在 ScheduleTab（位於 `src/AdminPage.jsx` 或獨立檔，由實作時 grep 確認）節目卡片內新增 `expanded` state + 展開按鈕；collapsed 時不觸發任何請求
- [x] 5.3 依 Decision "前端 polling 策略" 實作 `useTranscriptionStatus(showId, enabled)` hook：`enabled=false` 時返回 idle；`enabled=true` 時 `useEffect` 立即 fetch + `setInterval(fetch, 5000)`；cleanup 清 interval 並取消 in-flight request（可用 AbortController）
- [x] 5.4 展開面板內實作三個 region：ProgressCounts / currently_processing list / recent_failures list；空 list 顯示 muted placeholder（"目前沒有轉錄中" / "近期沒有失敗"）；失敗項目顯示 title + error_category badge + truncated error_message
- [x] 5.5 實作 `categoryToBadge(category, lang) -> {variant, label}` 共用函式（放 `src/Shared.jsx`），ScheduleTab 與 ExternalApiStatusTab 都 import 它，確保「一個 category 一個顏色」跨 UI 一致

## 6. 前端 AdminPage 外部 API 狀態 tab

- [x] 6.1 實作 Requirement: Admin page exposes an External API Status tab —— 在 `src/AdminPage.jsx` 的 tab 結構新增 `admin-external-api` 頁籤（label zh="外部 API 狀態" / en="External API Status"），並在 `App.jsx` 的 router page 值對應處新增 `admin-external-api`
- [x] 6.2 建 `src/ExternalApiStatusTab.jsx`：mount 時 fetch + `setInterval(fetch, 15000)`；unmount 或 tab 切走時 clearInterval；render 三張卡片（openai_whisper / openai_chat / openai_embedding）
- [x] 6.3 每張卡片顯示：API 人類可讀名、最近呼叫相對時間（寫 `formatRelativeTime(ts_ms, lang)` helper）、badge（呼 5.5 的 categoryToBadge）、HTTP status 區塊（僅當 latest.http_status 非 null）、degraded 時下方顯示 muted 警示
- [x] 6.4 空狀態：latest=null 時顯示 "尚無紀錄" / "No calls recorded yet"，不 render badge/timestamp/http_status

## 7. 部署與驗證

- [x] 7.1 commit + push；Zeabur 自動 build；backend 啟動時 alembic 自動 upgrade 加 transcripts.updated_at
- [x] 7.2 觸發一次轉錄（挑短集），確認 `api_health:openai_whisper` Redis key 有一筆 ok=true 紀錄（`redis-cli LRANGE api_health:openai_whisper 0 0`）
- [x] 7.3 手動讓 OpenAI key 無效（暫時改 env 為錯的）觸發一次轉錄，確認 `api_health:openai_whisper` 紀錄一筆 ok=false, error_category=auth_error；回復正確 key
- [x] 7.4 在後台展開 ScheduleTab 卡片，確認每 5 秒 devtools Network 都看到 transcription-status 請求；折疊後停止
- [x] 7.5 在後台進「外部 API 狀態」tab，確認三張卡片正確顯示近期狀態；切走 tab 後 Network 停 polling
