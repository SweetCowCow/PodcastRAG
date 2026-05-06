# PodcastRAG

> 對 Podcast 內容做語意搜尋與對話式查詢的 RAG 系統。
> A Retrieval-Augmented Generation system for semantic search and conversational Q&A over podcast transcripts.

線上服務 / Live: **https://app.podcastrag.app**

---

## 中文版

### 這是什麼？

PodcastRAG 是一個 Podcast 智慧查詢平台。它會自動抓取 RSS、用 Whisper 做逐字稿、切片向量化存進 pgvector，最後讓你用自然語言問問題，並把答案連回原始集數的時間點。

主要功能：

- **節目訂閱與自動轉錄**：貼上 RSS Feed，系統會自動抓集數、跑 Whisper 轉錄、產生每集 AI 摘要
- **語意搜尋**：跨集數跨節目找相關段落，免登入即可使用（IP 限流 20 次／日）
- **對話式 Q&A**：登入後消耗 quota 取得 LLM 整合答案，附引用片段
- **逐字稿閱讀器**：時間軸、說話者標記、關鍵字高亮，點段落跳回原音檔位置
- **後台管理**：API 金鑰、LLM 模型、RAG 參數、轉錄排程、quota 申請審核

### 技術架構

| 層級 | 技術 |
|------|------|
| 前端 | React 18（CDN + Babel Standalone，免打包）、JSX inline styles |
| 後端 | FastAPI、SQLAlchemy 2.0（async）、Alembic |
| 資料庫 | PostgreSQL + pgvector |
| 任務佇列 | Celery + Redis（worker / beat / dispatcher 三角色） |
| 轉錄 | faster-whisper |
| LLM / Embedding | OpenAI 相容 endpoint（可換 provider） |
| 認證 | Google OAuth 2.0 PKCE + session cookie + CSRF |
| Email | ZSend（Zeabur 自家 SES wrapper） |
| 部署 | Zeabur（Singapore region）+ Cloudflare DNS |

專案目錄：

```
PodcastRAG/
├─ index.html              # 前端入口（無打包）
├─ src/                    # React 元件（.jsx）
│  ├─ Shared.jsx           # TOKEN 設計 token + 共用元件
│  ├─ App.jsx              # 路由 / 登入 / 語言切換
│  ├─ PodcastSelect.jsx    # 節目選擇頁
│  ├─ QueryPage.jsx        # 查詢頁
│  ├─ TranscriptPage.jsx   # 逐字稿頁
│  └─ AdminPage.jsx        # 後台
├─ backend/
│  ├─ app/
│  │  ├─ api/              # FastAPI routers
│  │  ├─ services/         # RAG / 轉錄 / OAuth / RSS / Email…
│  │  ├─ workers/          # Celery tasks（轉錄 / 摘要 / quota digest）
│  │  ├─ models/           # SQLAlchemy ORM
│  │  └─ main.py
│  ├─ alembic/             # DB migrations
│  └─ requirements.txt
├─ openspec/               # Spectra 規格驅動開發（specs / changes）
├─ docs/roadmap.md         # 路線圖
├─ Dockerfile
└─ entrypoint.sh
```

### 路線圖

`docs/roadmap.md` 紀錄了完整的 Phase A→D 開發規劃（公開準備 → 品質基線 → RAG 優化 → 商業化）。

### License

本專案採用 **GNU AGPL-3.0**。
- 個人使用、學術研究、自架自用：自由使用與修改
- 任何形式的對外服務（包含 SaaS）：必須把修改後的程式碼也以 AGPL-3.0 開源
- 商用授權（不想開源）：請開 issue 聯絡

---

## English

### What is this?

PodcastRAG is a podcast intelligence platform. It ingests RSS feeds, transcribes episodes with Whisper, chunks and embeds them into pgvector, then lets you query with natural language — every answer cites the source episode and timestamp.

Highlights:

- **Auto-ingestion**: paste an RSS feed, the system pulls episodes, runs Whisper transcription, and generates per-episode AI summaries
- **Semantic search**: cross-show, cross-episode passage retrieval — no login required (IP rate limit 20/day)
- **Conversational Q&A**: signed-in users spend quota for LLM-grounded answers with inline citations
- **Transcript reader**: timeline, speaker labels, keyword highlights, click-to-seek
- **Admin console**: API keys, LLM models, RAG params, transcription scheduling, quota request review

### Stack

| Layer | Tech |
|-------|------|
| Frontend | React 18 via CDN + Babel Standalone (no build step), inline-style JSX |
| Backend | FastAPI, SQLAlchemy 2.0 async, Alembic |
| Database | PostgreSQL + pgvector |
| Queue | Celery + Redis (worker / beat / dispatcher) |
| Transcription | faster-whisper |
| LLM / Embeddings | OpenAI-compatible endpoint (provider-swappable) |
| Auth | Google OAuth 2.0 PKCE + session cookie + CSRF |
| Email | ZSend (Zeabur's SES wrapper) |
| Hosting | Zeabur (Singapore) + Cloudflare DNS |

### Roadmap

See `docs/roadmap.md` for the full Phase A→D plan (public-launch prep → quality baseline → RAG tuning → commercialization).

### License

Licensed under **GNU AGPL-3.0**.
- Personal, academic, and self-hosted use: free to use and modify
- Any networked service (including SaaS) must also be released under AGPL-3.0
- For a commercial license without open-sourcing your modifications, please open an issue
