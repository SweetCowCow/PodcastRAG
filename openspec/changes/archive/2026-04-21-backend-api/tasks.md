## 1. 專案初始化與設定管理

- [x] 1.1 建立 `backend/` 目錄結構：`app/`、`app/api/`、`app/models/`、`app/core/`、`alembic/`
- [x] 1.2 建立 `backend/requirements.txt`，加入 fastapi、uvicorn、sqlalchemy 2.0、asyncpg、alembic、pydantic-settings、pgvector 等依賴（配合「使用 FastAPI + SQLAlchemy 2.0 + Alembic」決策）
- [x] 1.3 建立 `backend/.env.example`，列出所有必填環境變數（`DATABASE_URL`、`FRONTEND_ORIGIN` 等）
- [x] 1.4 實作 `backend/app/core/config.py`：設定管理使用 pydantic-settings + .env（Configuration management via environment variables），缺少必填變數時拋出明確錯誤

## 2. FastAPI 應用程式骨架

- [x] 2.1 建立 `backend/app/main.py`：建立 FastAPI application entrypoint，掛載 CORS middleware，設定允許的前端 origin
- [x] 2.2 建立 `backend/app/core/database.py`：建立 async SQLAlchemy engine 與 session factory（使用 asyncpg driver，配合「使用 FastAPI + SQLAlchemy 2.0 + Alembic」決策）
- [x] 2.3 在 `backend/app/core/database.py` 實作 `get_db` dependency function，確保 async database session management（每個 request 一個 session，例外時 rollback 並關閉）
- [x] 2.4 建立 `backend/app/api/health.py`：實作 health check endpoint（`GET /health`），成功時回傳 `{"status": "ok", "database": "connected"}`，資料庫無法連線時回傳 HTTP 503

## 3. 資料庫 Schema 與 Migration

- [x] 3.1 確認本地 PostgreSQL 已安裝 pgvector extension，並在 `docker-compose.yml` 中使用內建 pgvector 的 image（pgvector extension enabled，配合「資料庫 Schema 設計（四張核心資料表）」決策）
- [x] 3.2 建立 `backend/app/models/show.py`：定義 shows table SQLAlchemy model（UUID PK、rss_url unique constraint）
- [x] 3.3 建立 `backend/app/models/episode.py`：定義 episodes table SQLAlchemy model（UUID PK、show_id FK、guid unique per show）
- [x] 3.4 建立 `backend/app/models/transcript.py`：定義 transcripts table SQLAlchemy model（episode_id unique FK、status enum）
- [x] 3.5 建立 `backend/app/models/transcript_segment.py`：定義 `transcript_segments` table SQLAlchemy model，包含 `vector(1536)` 欄位（transcript_segments table with pgvector）
- [x] 3.6 初始化 Alembic：`alembic init backend/alembic`，設定 `env.py` 指向 async engine 與所有 SQLAlchemy models
- [x] 3.7 產生並驗證 Alembic 初始 migration（Alembic migration baseline）：執行 `alembic upgrade head` 確認四張資料表（shows、episodes、transcripts、transcript_segments）皆正確建立

## 4. 本地開發環境驗證

- [x] 4.1 建立 `backend/docker-compose.yml`，包含 PostgreSQL + pgvector service，方便本地開發啟動資料庫
- [x] 4.2 啟動後端服務（`uvicorn app.main:app --reload`），呼叫 `GET /health` 確認回傳 `{"status": "ok", "database": "connected"}`
