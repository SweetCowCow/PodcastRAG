# Architecture Decisions

## Why

PodcastRAG 目前前端骨架已完成，但所有頁面跑在 Mock 資料上，無任何後端串接。為了讓系統能真實運作並部署至雲端，需要確定整體技術架構與開發優先順序。

## What Changes

- 建立 GitHub repository 進行版本控制
- 開發 Python + FastAPI 後端 API 層
- 在 Zeabur 部署前端（靜態 HTML）與後端（FastAPI）
- 使用 PostgreSQL + pgvector（on Zeabur）儲存逐字稿、集數資訊與語意向量
- 使用 Cloudflare R2 儲存音訊檔案（mp3 / m4a）
- 串接 RSS Feed 解析取得真實節目與集數資料
- 整合 Whisper 語音轉錄管線
- 實作 RAG 查詢後端

## Non-Goals

- 使用 Pinecone 等獨立向量資料庫（改用 pgvector 整合至 PostgreSQL）
- 使用 Node.js 後端（選定 Python 以利 Whisper 整合）
- 使用量統計 Dashboard（優先序最低，核心功能完成後再處理）

## Capabilities

### New Capabilities

- `github-setup` — GitHub repo 建立與版本控制設定
- `backend-api` — Python FastAPI 後端骨架與資料庫 schema
- `rss-feed` — RSS Feed 解析，取得節目與集數清單
- `transcription-pipeline` — Whisper 語音轉錄管線
- `rag-query` — RAG 語意查詢後端
- `zeabur-deployment` — Zeabur 雲端部署設定（前端 + 後端 + PostgreSQL）
- `cloudflare-r2` — 音訊檔案物件儲存

### Modified Capabilities

（無，目前尚無現有 spec）

## Impact

- 前端所有 `MOCK_*` 常數需逐步替換為真實 API 呼叫
- 後端新增 Python 專案結構（`backend/` 目錄）
- 需新增 `requirements.txt`、`Dockerfile` 或 Zeabur 設定檔
- Cloudflare R2 需獨立帳號與 API 金鑰設定
