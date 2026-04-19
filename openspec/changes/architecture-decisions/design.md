# Architecture Design

## Context

PodcastRAG 前端骨架（React 18 / CDN + Babel）已完成，包含節目選擇、查詢、逐字稿、後台管理四個頁面。目前全部使用 `MOCK_*` 假資料，無後端。目標是建立完整的雲端部署架構，讓系統能真實運作。

## Goals / Non-Goals

**Goals**
- 確定各層技術選型，避免日後架構翻轉
- 以最低複雜度完成雲端部署
- 資料儲存分層清楚（結構化、向量、二進位檔案）

**Non-Goals**
- 高可用性 / 多區域部署（個人專案規模）
- CI/CD pipeline 自動測試（初期手動 deploy 即可）
- 使用量計費系統

## Decisions

### 雲端平台選用 Zeabur

選 Zeabur 而非 Railway / Render / AWS：
- 台灣團隊維護，中文支援佳
- 從 GitHub 推送即自動部署，操作最簡單
- 同時支援靜態前端、Python 後端、PostgreSQL，一站搞定

### 後端選用 Python + FastAPI

選 Python 而非 Node.js：
- Whisper 語音轉錄、LangChain、OpenAI SDK 均為 Python 生態系
- FastAPI 效能接近 Node.js，且有自動 API 文件（Swagger UI）

### 資料庫選用 PostgreSQL + pgvector

選 PostgreSQL + pgvector 而非 PostgreSQL + Pinecone：
- 減少一個外部服務依賴（成本、複雜度）
- pgvector 支援 cosine similarity 搜尋，足夠應付 Podcast RAG 的規模
- Zeabur 上的 PostgreSQL 原生支援 pgvector 擴充

### 音訊檔選用 Cloudflare R2

選 R2 而非 AWS S3 / Zeabur Volume：
- 免費額度 10GB / 月，個人專案初期零成本
- S3 相容 API，Python boto3 可直接使用
- Zeabur Volume 不適合大型二進位檔案

## 整體架構

```
GitHub Repo
    │ push → 自動部署
    ▼
┌─────────────────────────────────┐
│            Zeabur               │
│  ┌──────────┐  ┌─────────────┐  │
│  │ 前端靜態  │  │  FastAPI    │  │
│  │  (HTML)  │  │  後端 API   │  │
│  └──────────┘  └──────┬──────┘  │
│              ┌─────────┘        │
│              ▼                  │
│  ┌─────────────────────────┐    │
│  │  PostgreSQL + pgvector  │    │
│  │  shows / episodes /     │    │
│  │  transcripts / vectors  │    │
│  └─────────────────────────┘    │
└─────────────────────────────────┘
          │ 音訊檔上傳 / 讀取
          ▼
┌──────────────────┐
│  Cloudflare R2   │
│  (mp3 / m4a)     │
└──────────────────┘
```

## 開發優先順序

1. **GitHub repo 建立** — 所有後續工作的前置條件
2. **RSS Feed 解析** — 第一個真實資料來源，驗證前後端串接
3. **FastAPI 骨架 + DB schema** — 建立後端基礎
4. **Whisper 轉錄管線** — 產生逐字稿資料
5. **RAG 查詢後端** — 核心功能
6. **Zeabur 部署設定** — 上線

## Risks / Trade-offs

- **pgvector 規模限制** → 若資料量超過百萬向量再考慮遷移至 Pinecone；初期無需擔心
- **Whisper 轉錄成本** → 使用 OpenAI Whisper API 按分鐘計費；可先用本地 Whisper 開發測試
- **Cloudflare R2 整合** → 需額外設定 CORS 與 presigned URL；FastAPI 負責產生，前端直接上傳

## Open Questions

- Whisper 要用 OpenAI API 還是自架本地模型？（影響轉錄成本與速度）
- 向量 embedding 要用哪個模型？（OpenAI text-embedding-3-small vs 本地模型）
