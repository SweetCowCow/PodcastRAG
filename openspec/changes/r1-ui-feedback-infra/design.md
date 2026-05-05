## Context

R1 評測框架第一塊（per `docs/research/r1-rag-eval-brief.md` 2026-05-05 議程結論）。本 change 只負責使用者直接訊號收集，不做評測本體。

當前 RAG query path（`backend/app/api/query.py` + `services/rag.py`）回傳 answer + sources，但前端沒有任何回送通道。R1.2 需要 thumbs-down 真實 case 補進 sentinel 題庫，因此 R1.1 必須先上線並累積數據。

Stakeholders：
- 主要使用者：登入會員（投 thumbs）
- 次要使用者：匿名訪客（送 citation_click）
- 維運：admin 看 7 日 thumbs ratio debug

## Goals / Non-Goals

**Goals**
- 收 thumbs vote（含可選 comment）並關聯到 query
- 收 citation 點擊事件（匿名也能收）
- 對外暴露 admin 用 7 日 thumbs ratio 統計
- 同 PR 收掉 LandingPage 兩個 paywall copy + 節目卡片樣式

**Non-Goals**
- 不做 RAG 評測（屬 R1.2）
- 不接 Langfuse trace（屬 R1.3）
- 不做泛用 events 查詢介面（本次只支援寫入 + 一個 event_type）
- 不做 thumbs ratio 圖表化（本次只是 debug 字串）

## Decisions

### Events 表用「通用 schema + 指定 event_type」設計

採用 `event_type VARCHAR + event_payload JSONB` 通用設計，本次只 enable `citation_click`。後續 R1.3 可以在不改 schema 的情況下加 `answer_view`、`scroll_depth` 等 event。Trade-off：JSONB 查詢慢，但本次寫多讀少（只 admin 偶爾掃），未來如果需要 dashboard 再加 materialized view。

替代方案 — 為每種 event 建獨立表。Reject：本次只 1 種，未來可能 5+ 種，每種一張表會爆。

### Citation 點擊用 navigator.sendBeacon

點 citation 後會跳轉 TranscriptPage（同一 SPA route 切換），用 fetch 可能在切 route 時被取消。`sendBeacon` 保證 fire-and-forget。fallback 用 fetch with `keepalive: true`。

### POST /events 公開但 IP rate limit 60/min/IP

匿名訪客也是訊號來源（landing page CTR），不能要求登入。但匿名 endpoint 有濫用風險，沿用既有 `ip-rate-limit` 機制（`auth/dependencies.py` 已有 `optional_auth_with_ip_limit`）但訂為 60/min/IP（events 比 query 頻繁）。Payload schema 用 Pydantic 嚴格校驗，避免亂塞 JSON。

### qa_feedback 同 query_id 可改投，不刪舊 row

每次投票寫新 row（不 UPDATE），加 index `(query_id, user_id, created_at DESC)`。讀的時候取最新一筆當「現在的投票」。好處：保留改投歷史可看 thumbs flip 模式。Trade-off：表會長，但 100 user × 30 query/day × 2 vote ≈ 6K rows/day，幾年沒事。

### 7 日 thumbs ratio endpoint at GET /qa-feedback/stats admin 限定

簡單 SQL aggregate，回傳 `{up_7d, down_7d, ratio}`。前端 QueryPage 在 admin role + query 結果存在時 fetch 一次。不做 cache（admin 用，量不大）。

### LandingPage 節目卡片改用 PodcastSelect 的 ShowCard

ShowCard 已存在於 `src/PodcastSelect.jsx`，需把它加進 `Object.assign(window, ...)` 暴露為全域，並調整 `index.html` 載入順序讓 PodcastSelect 在 LandingPage **之前** 載入。

替代方案 — 在 LandingPage 重複實作。Reject：違反 DRY，未來改一邊忘了改另一邊。

## Risks / Trade-offs

- [JSONB events 表後期查詢慢] → R1.3 視需要加 generated columns 或 materialized view
- [sendBeacon 在 Safari < 13 不支援] → fallback fetch keepalive；接受少量漏報
- [admin /qa-feedback/stats 回 0 票時前端要處理 NaN ratio] → 後端在 total=0 時回 `ratio: null`，前端對 null 顯示「（尚無資料）」
- [thumbs UI 對未登入使用者顯示] → 顯示 disabled 按鈕 + tooltip「登入後可投票」，不彈 Modal（避免打斷閱讀）

## Migration Plan

1. Alembic migration 新增 2 表（純 additive，無 downtime）
2. Backend deploy（4 service 都自動跑 `alembic upgrade head`）
3. Frontend deploy（cache bust QueryPage v→3、LandingPage v→2、PodcastSelect v→3）
4. Smoke test：手動投一票、點一個 citation、檢查 DB 有 row

Rollback：drop 2 表（無外部依賴）。Frontend 退到上一個 commit。

## Open Questions

無——議程已對齊。
