# PodcastRAG 路線圖

> 最後更新：2026-05-04（自有網域 podcastrag.app + ZSend 上線後）

本文件記錄 PodcastRAG 後續開發的優先順序與規劃。依 Phase 排序，**Phase A 阻擋公開最先**，再做評測基線，再優化 RAG，最後商業化。

---

## Phase A — 公開準備

| 代號 | 項目 | 狀態 |
|------|------|------|
| — | 競品分析（3 站：sear.newfolderla.com / findtt.top / whatmkreallysaid.com） | ✅ 已完成（產出在 `docs/research/`，未進 commit） |
| — | `admin-llm-step-config`（T3 前置）| ✅ 已 archive 並 deploy（2026-05-03，v0.7）— 重構 admin AI 設定為 `api_keys` + `ai_steps` 雙表 |
| — | `e2e-login-backdoor`（驗證流程基建）| ✅ 已 archive 並 deploy（2026-05-03，v0.8）— `/auth/_e2e_login` env-gated 後門讓 Claude MCP 自動驗證不再仰賴 14 天過期的 storage state |
| **T3** | 每集 AI 摘要（`episode-ai-summary`）| ✅ 已 archive 並 deploy（2026-05-03，v0.9）— map-reduce + idempotent + admin backfill |
| — | `summary-stale-detection`（T3 補強）| ✅ 已 archive 並 deploy（2026-05-04）— cron_tick 每分鐘掃 stale running summary、Celery on_failure handler、`ai_summary_started_at`/`ai_summary_error` 兩欄位 |
| **U1** | freemium 分層 gate（取代「全站登入 gate」原計畫）| ✅ 已 archive 並 deploy（2026-05-04，v1.0）— LandingPage、公開段落搜尋（IP rate limit 20/day）、登入解鎖 LLM 答案、quota 申請流程 |
| **O1** | 自有網域 + ZSend Email | ✅ 已上線（2026-05-04）— `podcastrag.app` 透過 Zeabur registrar 購買，前後端綁 `app./api.`，ZSend 整合 `noreply@podcastrag.app`。**SameSite=Lax 改動留為 polish change**（現 samesite=none 仍可運作；切 lax 需先廢棄 zeabur.app 子域）|

### T3：每集 AI 摘要（NEW，源自競品分析 A1）
- 批次跑 LLM 寫每集 80–150 字摘要（**不**做 `ai_display_title`，討論決定）
- DB 加 `episodes.ai_summary / ai_summary_status / ai_summary_generated_at / ai_summary_model`
- 轉錄完成後鏈式 enqueue Celery task；map-reduce（chunk=12K token，3 retries）
- 走 `ai_steps.summary` step 拿 endpoint / model
- UI 在 PodcastSelect / QueryPage / TranscriptPage 三處顯示，失敗 fallback 原 RSS 描述（對使用者隱藏）
- Admin Queue Tab 加 summary badge + 失敗重跑 + 「批次補摘要」一鍵
- 規模 32 tasks，成本一次性 657 集 < $1

### ~~U1：全站登入 gate + 註冊流程細化~~ → 已轉為 freemium 分層 gate（archive 2026-05-04）
- 改採「先讓人看到價值再要登入」設計：select/transcript 完全公開、段落搜尋免登入（IP rate limit 20/day）、LLM 答案需登入消耗 quota
- Google SSO 一鍵直接 active（無 pending / approval queue / email 驗證）
- Quota 用完不自動補回，使用者主動透過「申請更多額度」按鈕送 quota_requests
- Beat 每 12 小時彙整 pending 申請寄給 admin（ZSend 已開通，2026-05-04 起可實際寄信）

### ~~O1：自有網域 + SameSite=Lax~~ → 網域 + ZSend 上線（2026-05-04）；SameSite=Lax 留為 polish
- ✅ 透過 Zeabur registrar 購買 `podcastrag.app`（$14.99/yr，自動 Cloudflare DNS，Let's Encrypt cert）
- ✅ `app.podcastrag.app` 綁 frontend service、`api.podcastrag.app` 綁 backend service
- ✅ Google OAuth Console 加 `https://api.podcastrag.app/auth/google/callback` redirect URI
- ✅ 4 個後端 service env 更新：`FRONTEND_ORIGIN` 加新域、`GOOGLE_REDIRECT_URI` 切新域
- ✅ ZSend 啟用 + 加 sending domain `podcastrag.app`（SES region ap-northeast-1）+ 6 DNS records (3 DKIM + MX + SPF + DMARC) + API key 產出 + env 部署完
- ✅ ZSend URL bug 修正（commit `c0e88fc`：原本猜的 `zsend.zeabur.app/api/v1/send` 實際是 `api.zeabur.com/api/v1/zsend/emails`）
- ⏳ **未做**：cookie SameSite=none → lax（需先廢棄 `*.zeabur.app` 子域才能切，否則跨網域 fetch 不會帶 cookie）

---

## Phase B — 品質基線

| 代號 | 項目 | 說明 |
|------|------|------|
| **R1** | RAG 評測框架 | golden set + recall@K + regression。**必做**，否則 R2/R3 矇著眼改 |
| **U3** | 使用量追蹤 Dashboard + 熱搜 chip | admin 看誰在燒額度，每人查詢趨勢；🆕 含 A3：QueryPage 空狀態顯示 7 日熱搜 chip 引導新使用者 |

---

## Phase C — RAG 真正優化

⭐ **優先級拉到最前**（2026-05-07 review）：R1.2 baseline Recall@5 = **2.4%**，純語意檢索在 162 集 show 直接破功 — R3 是當前 product quality 最大瓶頸。

R3 拆三段做（每段都跑 eval baseline 對照升幅）：

| 代號 | 項目 | 依賴 | 說明 |
|------|------|------|------|
| **R3.1** ⏸ parked 2026-05-08 | Hybrid retrieval 核心（**~52 tasks，proposal+design+specs 完成等 apply**）| R1 ✅ | (a) Chunk 重定義：30-60s 時間窗 / 5-10 segments，segment gap 切點，前後 overlap 1-2 seg；(b) jieba 分詞 + tsvector + 自訂節目詞典（迪拉胖、顏色、顏社、台通...）；(c) pgvector + tsvector RRF 融合（純 SQL 即可，不引 LlamaIndex）；(d) **Episode `description` 也進 BM25 索引** — RSS 已收錄全 162 集 description（節目主寫的高品質 entity-dense 文字，含餐廳 / 來賓 / 主題 bullets），這是純 transcript 檢索拿不到的。⚠️ 切點要對齊 chunk 邊界以免破壞 R1.2 dataset anchor |
| **R3.2** | 兩層檢索 + topic segmentation（~25 tasks）| R3.1 | (a) **第一層 episode 篩選**：embed `description`（清過 HTML / 業配 boilerplate），先抓出 top-3-5 相關集，再進去找 chunk — RSS description 是現成 episode summary，不用再 LLM 重生（比 ai_summary 準）；(b) LLM topic segmentation per episode（gpt-4o-mini ~$0.01/集，全 show 一次性 backfill ~$2-3）標出 intro / 主題 / 業配 / outro，業配段檢索時降權；(c) per-segment topic tag 加進 metadata；(d) 三層 boost：episode 相關度 × topic 相關度 × chunk 相關度 |
| **R3.3** | Metadata filter + 多欄位 weighting（~15 tasks）| R3.2 | (a) 從 episode title 正則抽 `Ft.`/`Feat.`/`feat.` 後的來賓名 → episodes 表加 `guests` 欄位；(b) 日期 / 主題 metadata filter（2024 那集/馬世芳那集）；(c) BM25 多欄位 weighting：title > description > chunk text；(d) speaker 暫不做（要重轉錄 360 集太貴，留 P2）|
| **R2** | RAG 答案 prompt + citation + 段落呈現強化 | R1 | 🆕 含 A2：後端 sources 回應加 `before_text`/`after_text` 上下文；前端 `<SourceCard>` 加關鍵字高亮 + 「跳到這段聽」button（deep-link `TranscriptPage?t=秒`）+ 集數 AI 摘要連結 |
| **R4** | RAG 結果 cache | — | Redis hash key on 問題 + show + top_k + model。🆕 回應附 `cache_hit: bool` flag 給前端（dev 模式可顯示，學自競品 findtt.top） |

**故意排除（不放 R3）**：
- LlamaIndex / LangChain — 抽象封裝過厚、效能黑盒、新依賴。pgvector + tsvector + RRF 純 SQL 即可
- Whisper diarization speaker labels — 要重轉 360 集，影響 P2，暫緩
- ASR 錯字後處理 — 屬於 input quality 問題（T1 範疇），R3 是 retrieval 端問題，分開做

---

## Phase D — 內容生態

| 代號 | 項目 | 依賴 | 說明 |
|------|------|------|------|
| **T2** | 轉錄人工回報機制 | — | UI flag bad transcript + admin 看 report。⚠️ **輕量版**：段落右側 icon 三選一（轉錯/敏感/其他），不開放使用者直接改字（避免新資料庫站那種開放校對的維運成本 + 惡意風險） |
| **T1** | 轉錄 LLM 潤飾（已完成集數重跑降錯字） | T2 | — |
| **C1** | 持久化對話紀錄 | — | DB 表 + API + UI |

---

## Phase E — 商業化 / 進階

| 代號 | 項目 | 依賴 | 說明 |
|------|------|------|------|
| **U2** | 點數系統 + 計價 + 自動每月補回 | U1 | — |
| **C2** | 相關推薦機制（演算法 + UI） | C1 | — |
| **C3** | 內容權限分級（付費 tier 才看某些功能） | U2 | — |
| **A5** 🆕 | 整集對話入口（彩蛋級，源自競品分析） | R2 / R3 | TranscriptPage 浮動「問這集」按鈕，`/query` 多接 `episode_id` 限定向量檢索範圍 |
| **R5** | 向量化地端實作（self-host embedding，省 OpenAI 錢） | — | ⚠️ **規模大 + 資源限制**：要起 model service、Linode SIN 2vCPU/4GB 跑 BGE-small 可以但慢；可能要升級 VPS 或上 GPU。等真的有成本壓力再做 |

---

## Phase F — Ops / 體驗微調（隨時可插）

| 代號 | 項目 | 說明 |
|------|------|------|
| **O2** | Pre-built base image | build 從 10 分→30 秒 |
| ~~O3 → db-backup~~ ✅ | **archived 2026-05-07-db-backup（v1.3 milestone）** | 24h RPO / 30min RTO。每日 03:00 UTC pg_dump → age 加密 → Cloudflare R2 離站。月度 GHA 自動還原驗證。Manual smoke 全綠（restored 354/180826 = prod 354/180826，0% diff）。詳見 `docs/disaster-recovery.md` |
| **A4** 🆕 | 明亮（淺色）主題（源自競品分析） | Shared.jsx TOKEN 拆 DARK/LIGHT + ThemeContext + localStorage。優先級低，等使用者反映再做 |

---

## 小修補（不開 Spectra change，下次順手做）

（2026-05-04 全部清完）
- ~~Empty-state 的 `POST /shows` 提示改導向後台~~ ✅ 已做（PodcastSelect 已 routing 到 admin-rag）
- ~~AdminPage ApiKeysTab 接後端~~ ✅ admin-llm-step-config 時已接好
- ~~STATS_VECTORS_COUNT 估算值改 live fetch~~ ✅ 加公開 `GET /stats` endpoint，ReleaseLogPage + PresentationPage 都改 live-fetch
- ~~既有 admin pytest 沒帶 auth fixture~~ ✅ 已隨 authentication-system 補齊（剩下 `test_admin_llm_step_migration.py` 不需要 — 它測 migration，不打 API）

---

## 已 archive 變更（最近 5 個）

| Change | Archive 路徑 | 摘要 |
|--------|-------------|------|
| `episode-ai-summary` | `openspec/changes/archive/2026-05-03-episode-ai-summary/` | 每集自動 AI 摘要（v0.9）：alembic 加 4 欄到 episodes 表（status enum pending/running/done/failed），新 Celery task `generate_episode_summary` 用 tiktoken cl100k_base 切 12K-token chunks 跑 map-reduce → 80-150 字繁中摘要（透過 `ai_steps.summary` 拿 LLM endpoint，admin 預設設 gpt-5-mini）。`_mark_queue_finished` 鏈式 enqueue（摘要失敗不回寫 transcription_queue）。Admin 後台加 SummaryBadge / 重跑單集 / 批次補摘要按鈕；前台 QueryPage / TranscriptPage 顯示，失敗自動 fallback RSS description（D3 對使用者透明）。37/37 tasks。136/136 pytest。Release log v0.9。|
| `e2e-login-backdoor` | `openspec/changes/archive/2026-05-03-e2e-login-backdoor/` | `/auth/_e2e_login` env-gated 後門：HMAC token compare + 15 min session TTL + per-IP 5/60s rate limit + audit log，只有設 `E2E_LOGIN_TOKEN` 才註冊 route（沒設回 404）。Claude MCP 驗證流程改用此後門，不再依賴 14 天過期的 playwright storage state。順便把 UI 「Release Log」英文 label 改成「Change Log」（中文「更新日誌」不變）。41/41 tasks。119/119 pytest。Release log v0.8。 |
| `admin-llm-step-config` | `openspec/changes/archive/2026-05-03-admin-llm-step-config/` | 重構 admin AI 設定：`api_keys` 表（集中金鑰管理）+ `ai_steps` 表（5 個固定步驟 answer/rewrite/summary/embedding/transcription，每步驟挑 provider+model+key）。Migration 從 `llm_config` + `OPENAI_API_KEY` env 自動匯入。設計上分 Rev A/B 雙寫過渡，但部署當下發現 entrypoint 是 `alembic upgrade head` 兩個一起跑了 — 接受、prod 沒事，事後寫 case study + memory 規則 (`feedback_migration_entrypoint_check.md`)。Embedding 強制 OpenAI provider；transcription 可 admin 切換 openai/faster-whisper 不用 redeploy。52/52 tasks。103/103 pytest。Release log v0.7。鋪好下一個 `episode-ai-summary` 要用的 summary step 位子。|
| `deploy-resilience` | `openspec/changes/archive/2026-05-03-deploy-resilience/` | 部署重啟後 1-3 min 內自動把卡住的轉錄推回 pending；force-cancel 即使 celery_task_id null 也釋放 throttle slot；OAuth env 改 Optional + backend startup 才強制驗。Release log v0.6 |
| `authentication-system` | `openspec/changes/archive/2026-05-02-authentication-system/` | Google SSO + RBAC + 查詢額度 + Phase 1 gate（後台 + query）。中途修了 cross-subdomain CSRF cookie bug。Release log v0.5 |

---

## 維護規則

本文件與 Claude 的記憶檔案 `project_pending_changes.md` **互為鏡像**，更新時請同步維護兩邊。
