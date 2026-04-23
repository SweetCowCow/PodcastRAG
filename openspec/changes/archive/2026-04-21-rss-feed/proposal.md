## Why

目前前端 Podcast 節目與集數皆為 `MOCK_*` 假資料。需要讓使用者或管理者能透過 RSS Feed URL 匯入真實節目，並將集數資料同步至資料庫，作為後續語音轉錄與 RAG 查詢的輸入來源。

## What Changes

- 新增 RSS Feed 解析器：讀取標準 Podcast RSS 2.0（含 `itunes:` 延伸欄位），回傳結構化的節目與集數資料
- 新增節目管理 API endpoints：
  - `POST /shows` — 以 RSS URL 新增節目（同步解析並寫入 `shows` 表）
  - `GET /shows` — 列出所有節目
  - `GET /shows/{show_id}` — 取得單一節目
  - `DELETE /shows/{show_id}` — 移除節目（連同集數 cascade 刪除）
  - `POST /shows/{show_id}/sync` — 重新拉取 RSS，同步集數到 `episodes` 表（以 `guid` 去重）
  - `GET /shows/{show_id}/episodes` — 列出節目集數（支援分頁）
- 新增 Pydantic schemas 作為 API request/response 型別

## Non-Goals

- 不實作背景排程自動同步（屬 `transcription-pipeline` 或獨立 schedule change）
- 不處理 RSS 認證（Premium feeds）或 OPML 匯入
- 不做前端 UI 串接（前端仍維持 Mock，待本 change 完成後另行串接）
- 不更動 `shows` / `episodes` 資料表 schema（沿用 `backend-api` 已建立的結構）

## Capabilities

### New Capabilities

- `rss-feed`: RSS Feed 解析邏輯與節目/集數管理 REST API

### Modified Capabilities

（無，不動現有 spec 的 requirements）

## Impact

- 新增 `backend/app/services/rss_parser.py`（RSS 解析器）
- 新增 `backend/app/api/shows.py`（節目管理 endpoints）
- 新增 `backend/app/api/episodes.py`（集數列表 endpoint）
- 新增 `backend/app/schemas/`（Pydantic request/response models）
- 更新 `backend/app/main.py` 掛載新 routers
- 更新 `backend/requirements.txt` 加入 `feedparser` 和 `httpx`
