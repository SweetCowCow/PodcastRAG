<!-- SPECTRA:START v1.0.2 -->

# Spectra Instructions

This project uses Spectra for Spec-Driven Development(SDD). Specs live in `openspec/specs/`, change proposals in `openspec/changes/`.

## Use `/spectra-*` skills when:

- A discussion needs structure before coding → `/spectra-discuss`
- User wants to plan, propose, or design a change → `/spectra-propose`
- Tasks are ready to implement → `/spectra-apply`
- There's an in-progress change to continue → `/spectra-ingest`
- User asks about specs or how something works → `/spectra-ask`
- Implementation is done → `/spectra-archive`
- Commit only files related to a specific change → `/spectra-commit`

## Workflow

discuss? → propose → apply ⇄ ingest → archive

- `discuss` is optional — skip if requirements are clear
- Requirements change mid-work? Plan mode → `ingest` → resume `apply`

## Parked Changes

Changes can be parked（暫存）— temporarily moved out of `openspec/changes/`. Parked changes won't appear in `spectra list` but can be found with `spectra list --parked`. To restore: `spectra unpark <name>`. The `/spectra-apply` and `/spectra-ingest` skills handle parked changes automatically.

<!-- SPECTRA:END -->

# PodcastRAG 專案說明

## 語言規範

**所有回應請使用台灣用語繁體中文。** 技術術語可保留英文原文（如 RAG、API、RSS），但說明文字一律使用繁體中文。

## 專案概述

PodcastRAG 是一個 Podcast 智慧查詢系統，讓使用者透過 RAG（Retrieval-Augmented Generation）技術對已轉錄的 Podcast 內容進行語意搜尋與對話查詢。

## 技術架構

- **前端框架**：React 18（CDN + Babel Standalone，無需打包工具）
- **語言**：JSX（`.jsx` 副檔名）
- **樣式**：全部使用 React inline styles，設計 token 集中在 `src/Shared.jsx` 的 `TOKEN` 物件
- **介面語言**：支援中英雙語切換（`lang === 'zh'` 判斷）

## 專案結構

```
PodcastRAG.html          # 入口頁面，引用所有 JSX 元件
src/
  Shared.jsx             # 共用元件：TOKEN 設計 token、Icon、Badge、Btn、Input、TopNav
  App.jsx                # 主應用：路由、後台登入 Modal、語言切換、Tweaks 面板
  PodcastSelect.jsx      # 第一層：Podcast 節目選擇頁（網格卡片）
  QueryPage.jsx          # 第二層：查詢頁（對話 + 語意搜尋）、可調整寬度的集數面板
  TranscriptPage.jsx     # 第三層：逐字稿頁（時間軸、說話者、關鍵字高亮）
  AdminPage.jsx          # 後台管理：API 金鑰、LLM 模型、RAG 設定、轉錄排程
```

## 設計規範

### 色彩 Token（`TOKEN` 物件）
| Token | 用途 |
|-------|------|
| `TOKEN.bg` | 頁面底色 `#0b1120` |
| `TOKEN.surface` | 卡片、面板背景 `#131c2e` |
| `TOKEN.surfaceRaised` | 輸入框、懸浮元素背景 `#1a2540` |
| `TOKEN.surfaceBorder` | 邊框線 `#243050` |
| `TOKEN.accent` | 主題強調色 `#6366f1`（Indigo） |
| `TOKEN.text` | 主要文字 `#e2e8f0` |
| `TOKEN.textSecondary` | 次要文字 `#7c8fad` |
| `TOKEN.textMuted` | 淡化文字 `#4a5a78` |

### 共用元件
- **`<Btn>`**：支援 `variant`（primary / secondary / ghost / danger）、`size`（sm / md / lg）、`icon`
- **`<Badge>`**：支援 `variant`（default / success / warning / danger / muted）
- **`<Input>`**：支援 `icon`、`type`
- **`<Icon>`**：SVG 圖示，支援 `name`、`size`、`color`

### 路由（頁面狀態）
| `page` 值 | 對應畫面 |
|-----------|---------|
| `select` | 節目選擇頁 |
| `query` | 查詢頁（需 `selectedShow`） |
| `transcript` | 逐字稿頁（需 `selectedEpisode`） |
| `admin-api` | 後台 → API 金鑰 |
| `admin-llm` | 後台 → LLM 模型 |
| `admin-rag` | 後台 → RAG 設定 |
| `admin-schedule` | 後台 → 轉錄排程 |

## 後端 Celery Queue 模型

詳細見 `docs/celery-queues.md`。摘要：

- 四條 queue：`transcribe`（priority=9）、`topic`（=2）、`summary`（=2）、`control`（=5 預設）
- 單 worker 多 queue：`--queues=transcribe,topic,summary,control --concurrency=6`
- `task_default_queue="control"`：未設 route 的 task 自動走 control，不會消失
- 只支援 Redis broker（priority_steps 是 Redis 專屬實作）
- dispatcher 不再 set `status=running`；transcribe worker entry 自己 set + 5 min idempotency 視窗
- `transcription_queue.dispatched_at`：dispatcher 的 memo pad，防自身 race（同 row 連發兩 task）

## 重要開發注意事項

- **不需要打包**：直接用瀏覽器開啟 `index.html` 即可運行
- **新增元件**：共用元件放 `Shared.jsx`，並在檔案末尾的 `Object.assign(window, {...})` 匯出
- **模擬資料**：目前各頁面使用 `MOCK_*` 常數作為假資料，之後需串接真實 API
- **雙語支援**：所有使用者看得到的文字，都需提供 `zh`（繁體中文）和 `en`（英文）兩種版本
- **後台登入**：Google SSO（OAuth 2.0 PKCE）+ session cookie + CSRF 雙保險。env `ADMIN_EMAILS` 白名單裡的 email 第一次登入後自動為 admin

---

# 工作紀律規則（2026-05-10 加入，源自 /insights 報告）

## Verification Discipline

- **絕不**標記 verification / validation 任務完成除非真的跑了（browser check / 跑測試 / prod smoke）
- 如果 MCP / browser session 掛了，明確回報失敗 + 詢問 — 不要默默 mark complete
- Spectra changes：archive 前一定跑完 propose → apply → archive 全週期 + prod 驗證

## Background Tasks

- 長跑任務（bake-offs / backfills / batch evals）**必須用持久化 runner 啟動**（nohup / systemd / tmux / Celery）— 不要用 `run_in_background`，session 死它就死
- 永遠用 `stdbuf -oL` 或 `python -u` pipe log 避免 tail/pipe buffering 把輸出藏起來
- 驗證 process 還活著：檢查 PID + log 持續長大才宣稱「launched」

## Skills First

- 做 security scan / pptx 生成 / 其他重複任務之前，先用 `/skills` 列現有 skill，**用既有的別寫 ad-hoc 腳本**

## 內容發布工作流（2026-05-30 改為 on-demand）

- **模式**：Jacky 當下開口要 → Claude 直接產 `.docx` 草稿放 `docs/content/drafts/on-demand/` → Jacky 自己編輯 + 貼到平台發布
- **草稿格式**：一律 `.docx`，純文字風格（無 markdown 符號），命名 `YYYY-MM-DD_平台_主題.docx`
- **追蹤檔**：發完 Jacky 告知後，在 `docs/content/content-coverage.md` append 紀錄；A.3 是未用 case-study 庫存
- **排程提醒已全停**（podcastrag-daily-reminder-weekday / -weekend / -weekly-planning）。**不要主動催發文**
- `editorial-cadence-v2.md` 與 `throwback-series-plan.md` 保留作為主題參考，**不再**是按表執行的依據

## Secrets Hygiene

- **絕不**在 chat 印 env vars / DB password / token（不准 `env` / `printenv` / `cat .env`）
- rotate 憑證時要同時檢查 env 引用 **跟** literal-string 寫死兩種 backend config 用法
- CLI 互動模式失敗時可能 dump 整份 env 到 stdout（譬如 `zeabur variable create` 沒 -y）— 用 `--interactive=false` + `update` 子命令

---

## 後續開發規劃

- [ ] 串接 RSS Feed 解析（取得真實節目與集數資訊）
- [ ] 整合 Whisper 語音轉錄 API
- [ ] 整合向量資料庫（Pinecone / pgvector）
- [ ] 實作真實 RAG 查詢後端
- [ ] 後台使用量統計 Dashboard
- [ ] 全站登入 gate（Phase 2，現只 gate 後台 + query）
- [ ] 自動每月 quota 補回 + 點數計價
