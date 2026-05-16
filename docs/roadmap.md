# PodcastRAG 路線圖

> 最後更新：2026-05-16（R3.3 metadata-filter shipped；prod Recall@5 0.86 (n=28 chunk_id) + guest/rule-pattern enum 上線。下一動：`r3-3-chat-enum-grounding` 收 known limits → whisper-chunking-fix → R2.2 prompt redo）

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
| **R3.1** ✅ shipped 2026-05-08 | Hybrid retrieval 核心 | R1 ✅ | (a) Chunk 重定義：30-60s / 5-10 segments + 前後 1 seg overlap；(b) jieba 分詞 + tsvector + 自訂詞典 (29 詞 manual seed)；(c) pgvector + tsvector RRF 融合；(d) Episode description 進 BM25（556 集）。**結果**：episode-level Recall@5 從 2.4% → 23.8%（10x），Recall@20 = 62%。詳見 `docs/case-studies/r31-hybrid-retrieval-rollout.md`。**併入 R3.2 的 carry-over**：description chunks 在排序壓 transcript anchor (cap 或 down-weight)、通用詞 dict 條目造成 noise (節目名類)、eval metric 加 episode-level flag |
| **R3.2** ✅ shipped 2026-05-11~13 | 兩層檢索 + topic segmentation（4 個 changes 全 archive） | R3.1 | (1) `r3-2-two-layer-topic-seg` — topic seg backfill 全綠（保留 in prod）；two-layer routing 在 r3-5 被關掉；(2) `r3-2-retrieval-fix` — Phase 1 lever test 證實 Recall ceiling 結構性，**但結論被 r3-5 推翻**（測試集污染）；(3) `chunking-version-coexistence` — schema 已 ship；(4) `description-retrieval-prefer-v2` — prefer-v2 + RRF DISTINCT + P95 -56% 已 ship。詳見各 archive design.md 的「2026-05-13 archive follow-up」段 + `docs/case-studies/r32-routing-regression-2026-05-11.md`（5/13 follow-up 結論作廢）|
| **R3.4** ✅ shipped 2026-05-12~13 | text-embedding-3-large + dual-write | R3.1 | embedding model 從 `text-embedding-3-small` 升級到 `text-embedding-3-large`（3072 dim）。原本 ship gate（D4）作廢 — 真正瓶頸是 routing 不是 embedding，詳見 archive design.md D7 follow-up |
| **R3.5** ✅ shipped 2026-05-13 (v1.7) | 關掉 two-layer routing | R3.2 | `ENABLE_TWO_LAYER_ROUTING` env default 翻 false；同 archive 把 golden set audit 結果（移 36 LLM-auto 壞題、補 q05 EP66 anchor、加 staging 守門）固化；human-curated Recall@5 0.0625 → **0.4375 (7x)**、P95 2170ms（< 4500ms gate）。詳見 archive design.md D2-D7 |
| **R3.3** ✅ shipped 2026-05-16 (v1.7) | Metadata filter + 三池 BM25 + cross-episode enumeration | R3.2 ✅ | (a) RSS regex 抽 guests → `episodes.guests` JSONB + admin 編輯 tab（93/164 集有 guests）；(b) `episodes.title_tsvector` Python-side jieba populate（558 集 backfill）；(c) 三池 RRF（chunk 1.0 / desc 0.7 / title 0.5）weight 線上可調；(d) LLM `entity_extraction` step (gemini-2.5-flash-lite) 抽問句 guests+date，fail-open；(e) ChatResponse 加 `enumeration_episodes` + frontend EnumerationSection（guest 名 / date / 「[哪那]幾集」rule pattern 任一觸發）；(f) Prod fix：那/哪 widen + malformed JSON salvage。**Prod 驗證**：Recall@5 0.86 (n=28 chunk_id)，馬世芳/楊大正 enum 正確；title pool live 但對此 dataset 不換 top-K（weight 設計上保守）。**Known limits**：chat 答案文字未看到 enumeration list（會說 1 集但 list 顯示 2）、topic-only 不觸發列舉、rule-pattern 無 topic filter 回全 show — 下個 change `r3-3-chat-enum-grounding`。詳見 `docs/case-studies/r33-metadata-filter.md`|
| **R2.1** ✅ shipped 2026-05-10 | citation infrastructure（v1.6） | R1 | 後端 sources 回應加 4 欄位（before/after_text、highlights、ai_summary_excerpt + ai_summary_full）；前端 `<SourceCard>` 加關鍵字 indigo 高亮（加粗+底線）+ before/after 灰色上下文 + AI 摘要 60 字「展開」+「跳到這段內容」button；URL deep-link `?show_id=&episode_id=&t=` shareable / bookmarkable / reload-safe；description-source 卡按鈕改「打開該集」；URL 邊界錯誤靜默回首頁；LLM prompt 加拒答模式 + `[N]` citation contract；citation parser strip 無效 ref。**Faithfulness gate 重訂為軟 gate（≥ 0.50）**因 RCA 證實退步根因是 retrieval 15% recall + judge 對中文拒答打折，跟 UI 無關。詳見 `docs/case-studies/r21-rca-deep-2026-05-10.md` |
| **R2.2** | prompt 重做（待 R3.x + R1.3 完成）| R3.x / R1.3 | 等 retrieval 改善 + judge re-bake-off 完，回頭把 Faithfulness 拉回 ≥ 0.71；同時做 inline `[N]` 渲染、hover ↔ source 互動、popover 完整化、mobile bottom sheet、無障礙 ARIA |
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

## 進行中 changes（active，非 parked）

（2026-05-13 R3.2 milestone 全部 archive 收尾後清空 — 詳見下方「已 archive」段）

## Parked changes（7 個）

**今天的執行順序（2026-05-13 user 拍板）**：
1. ✅ R3.x 收尾家務（archive 4 個 R3.2-era stale changes）
2. ⏳ **C 軌**：擴 human golden set 到 n=30+
3. ⏳ `whisper-chunking-fix` (~12) — 80min 集 multipart 撞 25MiB chunk 沒生效 bug
4. ⏳ **R2.2 prompt redo** — Faithfulness 拉回（routing 已修，先量新 baseline 再決定 prompt 改動範圍）

其他 parked（待之後規劃）：

5. `celery-routing-and-dispatcher-fix` (F1, ~18) — EP20 互卡 + stale-detect 失效
6. `r3-3-metadata-filter` (~52) — 詳見 Phase C 表
7. `multi-provider-usage-monitoring` (~25) — admin AI Hub + OpenAI 用量觀測 + budget 告警
8. `task-failure-monitoring-and-circuit-breaker` (F2, ~31) — 失敗率告警 + 永久錯短路 + 斷路器（依賴 F1）
9. `backfill-progress-admin-tab` (~16) — admin Queue Tab 進度概覽（將合進「新節目 onboarding flow」討論）
10. `fix-eval-dataset-com-004-json-leak` (~7) — thisno-core-com-004 答案混 raw JSON

## 衍生待 propose

- **eval golden set 擴張到 曼報 + 壹加壹電台** — 各 ~30+ 題人工 sentinel，等本節目 30+ 題到位再啟動
- **新節目 onboarding flow（情境 B）** — admin 加 show 時看 cost preview + 必須 confirm + worker throttle + 進度面板；建議合進 `backfill-progress-admin-tab`
- **R3.x 候選未 propose**：列舉型查詢 / topic seg 自動類別建議 / segment_categories admin UI / 業配段降權 multiplier / dict weight_in_lexical_query 通用化
- **`eval-runner-dynamic-top-k`**（待 `eval-runner-enumeration-scope` ship 後 propose）— enumeration items 的 top_k 動態提到 `len(expected_episode_ids)`（或 1.2x），才能測 catalog-wide 召回真實上限。動機：q25 expected 25 集，固定 top_k=5 下 episode_set_recall 數學上限 0.20。影響面：retrieval cost / latency aggregation 都會變，需獨立 change 評估

---

## 已 archive 變更（最近 5 個，依時間反序）

| Change(s) | Archive 路徑 | 摘要 |
|-----------|-------------|------|
| **R3.5** `r3-5-disable-routing` + R3.4 + R3.2 milestone (6 個) | `openspec/changes/archive/2026-05-13-*` | **v1.7 milestone**：關掉 two-layer routing + 6 個 R3.x changes pair archive。Recall@5 (human-curated) 0.0625 → **0.4375 (7x)**、P95 2170ms。Golden set audit 移 36 LLM-auto 壞題、留 10 sentinel、加 staging 守門。各 archive design.md 都有「2026-05-13 archive follow-up」段說明 supersession 邏輯 |
| `r2-1-citation-infra` + `r2-1-followup-bugs` + `r2-1-prompt-fix` | `openspec/changes/archive/2026-05-10-r2-1-*` | citation infrastructure（v1.6）：search 結果加 highlights / before/after_text / ai_summary 60 字 + 「展開」+「跳到這段內容」button + URL deep-link shareable + LLM prompt 加拒答模式 + citation parser strip [N]。**Faithfulness gate 重訂為軟 gate（≥ 0.50）**因 RCA 證實退步根因是 retrieval recall 15% + judge 對中文拒答打折，跟 UI 無關。Case study `docs/case-studies/r21-rca-deep-2026-05-10.md` |
| `db-backup` | `openspec/changes/archive/2026-05-07-db-backup/` | 每日 03:00 UTC pg_dump → age → R2 離站；月度 GHA 還原驗證；7d/4w/12m retention。月成本 ~$1。Release log v1.3 |
| `freemium-onboarding` | `openspec/changes/archive/2026-05-04-freemium-onboarding/` | LandingPage + 公開段落搜尋（IP rate limit 20/day）+ 登入解鎖 LLM 答案 + quota 申請流程。Release log v1.0 |
| `summary-stale-detection` | `openspec/changes/archive/2026-05-04-summary-stale-detection/` | cron_tick 每分鐘掃 stale running summary 重置 + 重 enqueue。Release log v0.9 |
| `episode-ai-summary` | `openspec/changes/archive/2026-05-03-episode-ai-summary/` | 每集 AI 摘要 80-150 字繁中，map-reduce + per-batch commit + admin 批次補摘要 button。Release log v0.9 |

完整列表（含更早）見 `openspec/changes/archive/` 目錄。

---

## 維護規則

- 本文件與 Claude 的記憶檔案 `project_pending_changes.md` **互為鏡像**，更新時請同步維護兩邊（feedback_roadmap_dual_write）
- 路徑變更 / 新增 / archive 時兩處都要動
- 詳細工作紀錄類文件（case studies / research）放 `docs/case-studies/` + `docs/research/`，**不進 commit**（feedback_case_studies_no_commit）

## 工作紀律（不在路線圖內，但執行時受其約束）

- **成本紀律**：pilot < $20 免問；> $30 大規模回填要 confirm；AI Hub 可程式查餘額（Balance/100k=USD），OpenAI 走 α 方案手動回報（baseline 記在 memory `reference_openai_balance.md`）
- **單節目 pilot 策略**：所有「全 corpus 重做」類動作（re-chunking / re-embed / 換 embedding model）必須先在單一節目（「這又沒有很屌」）pilot 驗證，再 rollout 其他兩個節目
