## Context

PodcastRAG 前端骨架（React 18 + CDN）已完成，所有頁面目前使用 `MOCK_*` 常數。後端需要從零開始建立，選定 Python FastAPI 作為框架，以利後續整合 Whisper 語音轉錄。資料庫使用 PostgreSQL + pgvector（部署於 Zeabur）。

## Goals / Non-Goals

**Goals:**
- 建立可本地開發、可部署至 Zeabur 的 FastAPI 後端骨架
- 定義完整資料庫 schema（節目、集數、逐字稿段落）並支援 pgvector
- 提供 Alembic migration 機制，確保 schema 版本可追蹤
- 提供 `/health` endpoint 驗證後端服務正常

**Non-Goals:**
- 不實作任何業務邏輯 API（RSS、Whisper、RAG 屬後續 change）
- 不建立前端與後端的串接（前端仍維持 Mock 資料）
- 不設定 Zeabur 部署（屬 `zeabur-deployment` change）

## Decisions

### 使用 FastAPI + SQLAlchemy 2.0 + Alembic

選擇 FastAPI 作為後端框架，搭配 SQLAlchemy 2.0（async）與 Alembic migration。

- **為何 FastAPI 而非 Flask**：FastAPI 原生支援 async/await，適合後續 Whisper 轉錄的長時間任務；內建 OpenAPI 文件；型別驗證使用 Pydantic。
- **為何 SQLAlchemy 2.0**：原生 async 支援（`asyncpg` driver）；與 Alembic 整合成熟。
- **替代方案**：Tortoise ORM — 棄用，生態系較小且 Alembic 支援不完整。

### 資料庫 Schema 設計（四張核心資料表）

```
shows           — Podcast 節目基本資料
episodes        — 集數（屬於 show）
transcripts     — 逐字稿（屬於 episode，一對一）
transcript_segments — 逐字稿段落（屬於 transcript，包含 vector embedding）
```

`transcript_segments` 使用 `pgvector` 的 `vector(1536)` 欄位儲存 OpenAI text-embedding-3-small 向量（1536 維）。

- **為何段落層級而非整集**：RAG 查詢需要精確定位到時間段，段落層級可提供更精準的上下文。
- **替代方案**：整集向量 — 棄用，語意搜尋精度不足。

### 設定管理使用 pydantic-settings + .env

使用 `pydantic-settings` 讀取 `.env` 檔案，所有設定（資料庫 URL、API 金鑰等）從環境變數注入，不硬編碼於程式碼中。

## Risks / Trade-offs

- **pgvector 本地開發**：開發者需在本地 PostgreSQL 安裝 pgvector extension，有一定設定門檻。→ 緩解：提供 `docker-compose.yml` 內建 pgvector 版 PostgreSQL image。
- **async SQLAlchemy 複雜度**：async session 管理比 sync 版複雜，容易出現 session leak。→ 緩解：使用 dependency injection 統一管理 session 生命週期。
- **Schema 演進**：早期 schema 決策（如向量維度 1536）未來可能需調整。→ 緩解：Alembic migration 確保可版本控制地變更 schema。
