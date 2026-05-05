## Why

R1 評測框架（per 2026-05-05 議程決議，brief 在 `docs/research/r1-rag-eval-brief.md`）需要使用者直接訊號：thumbs up/down 與 citation 點擊率。這是 R1 三個 change 中第一個（R1.1 → R1.2 → R1.3），先把訊號收集 infra 鋪好，後續 R1.2 的 sentinel 題庫才能挖到「真實抱怨案例」。同時順手收掉 LandingPage 兩個 paywall copy 微調與節目卡片樣式回退。

## What Changes

- **DB 新增 2 張表**：
  - `qa_feedback`：登入使用者對 AI 答案投 👍/👎 + optional comment
  - `events`：通用事件記錄表，本次只用一個 event_type=`citation_click`，payload 含 query_id / chunk_id / position
- **Backend 新增 2 個 endpoint**：
  - `POST /qa-feedback`（登入限定，可改投同一 query_id）
  - `POST /events`（公開，IP rate limit 60/min/IP，payload schema 校驗）
- **Frontend QueryPage**：
  - AI 答案下方加 👍 / 👎 button 群（投完按鈕變色顯示「已收到」並可改投）
  - 👎 點擊後展開 optional comment textarea + 送出
  - SourceCard / Citation card 點擊時 fire navigator.sendBeacon → POST /events
  - admin role 看到 query 結果時顯示「7 日 thumbs ratio」debug 字串（讀 `/qa-feedback/stats` 內部 endpoint，僅 admin 可呼叫）
- **LandingPage minor polish**（同次 PR）：
  - paywall h2 刪掉「（一次性免費額度，用完可申請補充）」括號文案
  - paywall 副標改成「瀏覽逐字稿、看相關段落都不用登入。只有「請 AI 統整回答」需要登入使用額度。」
  - 節目卡片改用 `PodcastSelect` 既有 `<ShowCard>`（顯示 logo / lang badge / 描述 / 集數+轉錄數 / 進度條 / RSS / 進入節目連結）

## Non-Goals

- **不寫 RAG 評測本體**（Recall@K / Faithfulness 等屬於 R1.2）
- **不接 Langfuse**（屬於 R1.3）
- **不做 admin Dashboard 卡片視覺化**（thumbs ratio 在本 change 只用 debug 字串，圖表化屬於 R1.3 polish）
- **不建 golden set / judge bake-off**（屬於 R1.2）
- **events 表不做泛用查詢介面**（本次寫死 `citation_click` 一種）

## Capabilities

### New Capabilities

- `qa-feedback`：使用者對 AI 答案投票與 comment 的資料模型、API、UI
- `client-events`：前端事件回送基礎建設（本次承載 citation_click，後續可擴展其他 event_type）

### Modified Capabilities

- `db-schema`：新增 `qa_feedback` 與 `events` 兩張表
- `rag-query`：QueryPage AI 答案區塊新增 thumbs UI 與 SourceCard click 回送
- `landing-page`：paywall copy 調整、節目卡片改用 ShowCard

## Impact

- Affected specs: qa-feedback (new), client-events (new), db-schema (modified), rag-query (modified), landing-page (modified)
- Affected code:
  - New:
    - backend/alembic/versions/xxxx_add_qa_feedback_and_events.py
    - backend/app/models/qa_feedback.py
    - backend/app/models/event.py
    - backend/app/api/qa_feedback.py
    - backend/app/api/events.py
    - backend/app/schemas/qa_feedback.py
    - backend/app/schemas/event.py
    - backend/tests/test_qa_feedback_api.py
    - backend/tests/test_events_api.py
  - Modified:
    - backend/app/main.py
    - backend/app/models/__init__.py
    - src/QueryPage.jsx
    - src/LandingPage.jsx
    - src/PodcastSelect.jsx
    - index.html
