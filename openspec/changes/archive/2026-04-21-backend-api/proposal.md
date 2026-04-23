## Why

PodcastRAG 前端骨架已完成，但目前所有資料皆為 Mock 假資料，無法真實運作。需要建立 Python FastAPI 後端骨架與資料庫 schema，作為後續 RSS 解析、Whisper 轉錄、RAG 查詢等功能的基礎。

## What Changes

- 建立 `backend/` 目錄，包含 FastAPI 應用程式結構
- 定義 PostgreSQL 資料庫 schema（節目、集數、逐字稿、向量索引）
- 設定 pgvector extension 支援語意向量搜尋
- 建立資料庫 migration 機制（Alembic）
- 提供基本 health check API endpoint
- 建立 `requirements.txt` 與本地開發環境設定（`.env.example`）

## Capabilities

### New Capabilities

- `backend-core`: FastAPI 應用程式骨架、設定管理、資料庫連線、health check endpoint
- `db-schema`: PostgreSQL 資料庫 schema，包含 shows、episodes、transcripts、transcript_segments 資料表，以及 pgvector extension

### Modified Capabilities

（無）

## Impact

- 新增 `backend/` 目錄（Python 專案結構）
- 新增 `backend/requirements.txt`
- 新增 `backend/.env.example`
- 新增 `backend/alembic/` 目錄（資料庫 migration）
- 前端未來需將 `MOCK_*` 常數替換為真實 API 呼叫
