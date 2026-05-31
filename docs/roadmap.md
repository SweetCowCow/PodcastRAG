# PodcastRAG 路線圖

> 最後更新：2026-05-31 晚（`per-show-mode-example-prompts` ✅ archive + prod 驗證上線 — 每節目×每模式 LLM 預產引導範例 + 冷啟動 chip fallback；後端新表 + 生成服務 + GET/backfill endpoint + summary 鏈式，前端 per-mode placeholder + TrendingQueriesChips fallback。prod 三節目 backfill 3/3/3、修掉 chat 長題被 60 字上限濾掉的缺陷。同 session 先完成 `unified-segment-citation-card`（三模式共用片段卡）。剩 parked 1 條 `voyage-rerank-tune-b22-b23`。下動候選：Tier 1 `chunk-level-retrieval-rca-b20-style` RCA／`semantic-topk-bump-and-show-more`／unpark voyage。**兩條 release log entry 待補**）

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
| **R3.3** ✅ shipped 2026-05-16 (v1.7) | Metadata filter + 三池 BM25 + cross-episode enumeration | R3.2 ✅ | (a) RSS regex 抽 guests → `episodes.guests` JSONB + admin 編輯 tab（93/164 集有 guests）；(b) `episodes.title_tsvector` Python-side jieba populate（558 集 backfill）；(c) 三池 RRF（chunk 1.0 / desc 0.7 / title 0.5）weight 線上可調；(d) LLM `entity_extraction` step (gemini-2.5-flash-lite) 抽問句 guests+date，fail-open；(e) ChatResponse 加 `enumeration_episodes` + frontend EnumerationSection（guest 名 / date / 「[哪那]幾集」rule pattern 任一觸發）；(f) Prod fix：那/哪 widen + malformed JSON salvage。**Prod 驗證**：Recall@5 0.86 (n=28 chunk_id)，馬世芳/楊大正 enum 正確；title pool live 但對此 dataset 不換 top-K（weight 設計上保守）。**Follow-up `r3-3-chat-enum-grounding` ✅ shipped 同日**：chat 答案 grounding（楊大正 chat 文字「1 集」→「2 集」對齊）+ topic-trigger（「歌單」單獨輸入也觸發列舉）+ topic-filter SQL（「歌單哪幾集」回 23 集精準而非全 164 集）+ tool-like 拆分（為 agentic RAG 預留）+ 前端階段式 10 集顯示。詳見 `docs/case-studies/r33-metadata-filter.md` Stage 8|
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

## Active + Parked changes（2026-05-31 snapshot）

**Active**（0 個）：
- （per-show-mode-example-prompts 已 2026-05-31 archive，無進行中 change）

**Parked**（1 個）：
1. `voyage-rerank-tune-b22-b23` (0/9) — 對 retrieval-rerank-via-voyage 的 b22/b23 調參。

**待 propose / 待 discuss**：見下方「衍生待 propose」段。

> 早期擱置的 `agentic-framework-bakeoff` / `chat-agentic-tool-routing` / `landing-and-mode-orchestration-redesign` / `rag-vs-longcontext-benchmark` 等：landing-redesign 已 2026-05-23 archive；其餘 agentic 路線仍在「衍生待 propose」追蹤，未進現役 parked queue。

## 衍生待 propose（未開 change 但有共識）

- ❌ **`retrieve-quality-step1-idf-and-prefilter`** done 2026-05-28 **FAILED, both layers reverted** (archive `2026-05-28-retrieve-quality-step1-idf-and-prefilter`)：Layer A (IDF-bucketed `ts_rank`) chunk_recall 0.482 → 0.382 ❌；Layer B (chat agent EP-ref dispatch prompt) chunk_recall 0.482 → 0.340 ❌。Root causes：(1) show-wide IDF 對 podcast transcript 不適用（entity token 在 show 維度罕見、在 answer-ep 內部極常見、IDF rare=signal 假設破滅）(2) prompt change 從來不 orthogonal 於 retrieval — 新 prompt 改 agent 措辭 `search_*(query: str)` 的 query → ts_rank 跟著飄 (3) show-wide DB probe 是 episode-scoped retrieval false positive validator。完整 RCA + 三條教訓 memory：`feedback_idf_show_wide_failed_2026_05_28.md` + `feedback_prompt_change_retrieval_side_effect.md` + `feedback_show_wide_probe_false_positive.md`。下動 pivot 評估框架升級（不再動 retrieval / prompt 直到有 span-level tracing + per-question tool trace）
- ✅ **`eval-framework-upgrade`** done 2026-05-30（archive `2026-05-30-eval-framework-upgrade`）— Langfuse Cloud Free + PG eval_traces 雙 sink + 6 個新 grader (4 DeepEval 內建 + 2 GEval 自寫) + `_calibration_8.json` + `retrieve_probe.py` + `prompt_fingerprint_diff.py` + PR template Retrieval/Prompt checklist + runbook + 全 34 baseline。**未達 4.4 acceptance**：prod 灰度 P95 +3375ms FAIL (<100ms gate)、tracing 預設 OFF、open follow-up `langfuse-self-host-evaluation`。完整 case study + RCA: `docs/case-studies/eval-framework-upgrade-2026-05-30.md`
- ❌ ~~**`langfuse-self-host-evaluation`**~~ — **CLOSED 2026-05-30** by `langfuse-sdk-overhead-rca`。Cloud SDK overhead 真實值 0.947 ms/span（30 span ~28ms）、與 Langfuse 官方 0.1ms 量級一致。4.4 P95 +3.4s attribution 錯誤、cross-session noise 造成的假象。完整 RCA: `docs/case-studies/langfuse-sdk-overhead-rca-2026-05-30.md`
- ✅ **`eval-runner-eval-context-plumbing`** done 2026-05-31（archive `2026-05-31-eval-runner-eval-context-plumbing`）— bind_eval_context FastAPI dependency + runner X-Eval-* 三 header 注入 + run_id 落 result JSON + `sql_rca_demo.py` + `prompt_fingerprint_diff.py --source=sql` 路徑。Phase 5 prod 驗 34 span / 8 item / mt03 三輪 locator NOT NULL。hotfix `842d69d` 修 span_writer JSONB serialization（dormant bug）。完整 case study: `docs/case-studies/eval-runner-eval-context-plumbing-2026-05-31.md`
- ✅ **`lexical-bm25-replace-ts_rank`** / **EP-scoped IDF** 候選**解凍**（原暫不開）— eval framework 已 ship，可重新討論。下次提案 design 階段必須含 `retrieve_probe.py` 對 calibration_8 八題的事前 dry-run 才能進 apply
- ✅ **`b23-dataset-and-retrieval-rca-fix`** done 2026-05-27（commits `927fa18` + `f2bd784`）— b23 chunk_recall 0→0.5（dataset GT 修正主因）；episode_finders.find_episodes_by_topic 加 guest-index dispatch path（≥2 distinct guest names 觸發）+ envelope `prefilter_source` 觀測欄位；admin diagnose 擴 top_n=500 + chunking_context；揭露 b20 retrieve_hybrid 召回根本性 miss（@1790/@1808 連 top-500 都沒撈到）留 follow-up `chunk-level-retrieval-rca-b20-style`
- **`chunk-level-retrieval-rca-b20-style`**（衍自 b20 Phase 3 diagnostic）— retrieve_hybrid 對 EP134 @1790.18 / @1808.78 在 top-500 都沒撈到，疑似 chunking 邊界或 lexical 召回根本問題；先 query prod DB `transcript_chunks WHERE episode_id=c1d87278 AND start_time BETWEEN 1780 AND 1820` 看 chunks 存在性
- **`agent-pronoun-grounding`**（follow-up，未急）— b23 揭露 agent 拿到無關 chunk 後 LLM 自動把代詞「他/她/我」解析成 query 主體 → 表面 grounded 實際 hallucinate；需 SYSTEM_PROMPT 或 grounding rule 加「代詞解析驗證」。**unblocked**（judge 已可量代詞 hallucination）
- ✅ **`judge-pronoun-attribution-check`** done 2026-05-27（eval-only 不 redeploy）— judge 改餵 result_full + 加 pronoun_attribution_check 三態指標 + b23 為 Example 4；新 baseline `baseline-post-judge-v2-2026-05-27.json` chunk_recall_grouped 0.382→0.482、factual 0.831→0.892、refusal 0.971→1.000 全部提升；0 hallucinated case 反映 dataset + retrieval 前置 fix 真實效果
- **eval baseline 寫死**：cross_episode mean chunk_recall **0.283**（舊 0.244 deprecated，污染期 citation collector bug 數據）
- ✅ **`citation-display-unify`** — **已於 2026-05-18 ship**（隨 landing-and-mode-orchestration-redesign decision 5 + ConversationSourcePanel）：列舉題走 EnumerationSection 主從佈局、內容題走 ConversationSourcePanel 依集分組。此條先前誤列為待辦（drift），2026-05-31 更正。**後續迭代** → 見下方兩個 2026-05-31 propose 的 parked change。
- ✅ **`unified-segment-citation-card`** done 2026-05-31（archive `2026-05-31-unified-segment-citation-card`）— 三模式共用片段卡 + 播放/跳轉兩鈕 + 顯示數量與 top_k 解耦 + 列舉題展開片段卡。prod 三模式 smoke 全綠。
- ✅ **`per-show-mode-example-prompts`** done 2026-05-31（archive `2026-05-31-per-show-mode-example-prompts`）— 每節目×每模式 LLM 預產引導範例 + 冷啟動 chip fallback。prod 三節目 backfill 3/3/3、前端 placeholder+chip smoke 全綠。
- **eval golden set 擴張到 曼報 + 壹加壹電台** — 各 ~30+ 題人工 sentinel，等本節目 30+ 題到位再啟動
- **R3.x 候選未 propose**：topic seg 自動類別建議 / segment_categories admin UI / 業配段降權 multiplier / dict weight_in_lexical_query 通用化
- 🆕 **`semantic-topk-bump-and-show-more`**（2026-05-31 user 問起）— 語意搜尋現顯示 8 筆＝`PublicSearchRequest.k` default 8（`schemas/query.py:182`，API 已支援 1–50；`rag.py` `RETRIEVAL_TOP_K=8`）；前端 `handleSearch` 沒傳 k。retrieval 是 pgvector 向量搜尋、只有 query embedding 一次固定成本，回 8 vs 30 筆成本幾乎一樣（**非每筆 LLM**）。候選：default 提到 ~15–20，或加「顯示更多」漸進載入（再 query 較大 k）。屬顯示深度調整、不動 ranking，風險低但仍應獨立 change（含 eval 對照）。`SemanticResultList` 目前無顯示 cap（全部渲染），需配合加 cap+show-more 才不會一次傾倒。
- **R2.2 prompt redo** — Faithfulness 拉回（依賴 R3.x + R1.3）
- **R1.3 judge re-bake-off** — Phase B，等 R3.x 全跑完啟動
- **Golden set audit q25 expected 對齊** — 4 集多撈 / 6 集漏，人工複查（屬 dataset quality）
- **Rule pattern 涵蓋率月度回顧** — 等真實 prod query 累積後做
- **`eval-runner-dynamic-top-k`** — enumeration items top_k 動態提到 `len(expected)`
- **`rag-py-module-split`** — `backend/app/services/rag.py` 已 1330 行，拆成 retrieve / rerank / aggregation / prompt 等獨立 module。**併進 `chat-agentic-tool-routing` 主 change 一起做**（那 change 本就會動 rag.py 內部結構，避免做兩遍）

---

## 已 archive 變更（最近，依時間反序）

| Change(s) | Archive 路徑 | 摘要 |
|-----------|-------------|------|
| **2026-05-31** `per-show-mode-example-prompts` ✅ done + 上線 | `openspec/changes/archive/2026-05-31-per-show-mode-example-prompts/` | 9/9 task done。每節目×每模式 LLM 預產引導範例（冷啟動 trending<3 fallback）。後端：`show_example_prompts` 表（migration `d8e9f0a1b2c3`）+ `services/example_prompts.py`（gather_materials + generate_for_show，沿用 summary step、fail-open、idempotent delete-then-insert、**per-mode 題目長度上限** index30/semantic70/chat120）+ 公開 GET `/shows/{id}/example-prompts` + admin backfill（單一 inline / 全 show enqueue）+ `workers/example_prompts_task.py` 鏈式（summary 批次全完成 enqueue 一次）。前端：i18n 三 per-mode placeholder + `TrendingQueriesChips` 加 mode prop（trending≥3 熱搜 / <3 fallback「範例」chip）+ QueryPage 三 tab 接線。本機 9 pytest 全綠 + migration 升降可逆。**Prod 驗證**：三節目（這又沒有很屌/曼報/壹加壹電台）trending 皆 0 全冷啟動，backfill 後各 3/3/3；前端三模式 placeholder + 範例 chip + 點擊執行全綠。順手抓到並修：全域 60 字上限把 chat 長題全濾掉（壹加壹電台 chat 0→3，commit `ed56f1b`）。生成內容抓到 ASR 錯字「寰宇龍虎報→豹」（非本 change bug，入 ASR backlog）。commits `71f2e44` + `ed56f1b`。 |
| **2026-05-31** `unified-segment-citation-card` ✅ done + 上線 | `openspec/changes/archive/2026-05-31-unified-segment-citation-card/` | 11/11 task done。三模式（索引/語意/對話）引用呈現收斂到單一共用葉子 `src/SegmentCitationCard.jsx`：片段文字 + 雙模式高亮（多詞兩色橘實線/青虛線 ← `highlightTerms` 移入本檔成 canonical、KeywordResults 不再重複宣告 / server `highlights` 單色 indigo via `.scc-server-hl` scoped CSS）+ 集標題 + 時間戳 +「播放此段」/「跳到逐字稿」兩顆獨立鈕（取代舊 `onSourceJump` 播放+導航綁一起）。`SourceCard` 改 thin wrapper 轉呼叫；`SemanticResultList`（relevance bar 移進卡內 `relevance` prop）/`ConversationSourcePanel`（每組 cap 5 + 顯示更多、與 top_k 解耦）/`KeywordResults`（T1/T2/T3 leaf）全換共用卡；`EnumerationSection` 集卡加「展開查看各段」inline 片段卡（不離頁）。`LANGUAGE.md` 補引用片段卡 + citation/source/segment 三層語意。Spec：segment-citation-card 新增 + conversation-source-panel/semantic-mode-result-ui 修改進 canonical（added 5/modified 3）。本機整合（9 元件 global、無 collision/JS error）+ prod 三模式 smoke 全綠（索引 T2 展開 25 卡兩色、語意 8 卡 relevance bar 100/87/74、對話 5 集分組 description「打開該集」vs transcript「播放+跳轉」、列舉「歌單哪幾集」展開 8 inline 卡）。commit `50388d9`。 |
| **2026-05-31** `keyword-index-mode` ✅ done + 上線 | `openspec/changes/archive/2026-05-31-keyword-index-mode/` | 26/26 task done。第三模式「索引」：`POST /shows/{id}/keyword-search` 嚴格 AND 多關鍵字三段式（T1 同 chunk AND / T2 跨三池 episode AND / T3 OR fallback 僅 T1+T2=0）+ 100 cap + 5s timeout；`app_settings.keyword_t2_collapse_threshold`（migration `c7d8e9f0a1b2`）；`KeywordResults.jsx` sectioned 結果頁（兩色高亮、T2 inline 展開查看各段、collapse chip、分頁、empty state、mode switcher）；QueryPage 索引 tab 接線。本機 20 unit+integration 測試（真實 Postgres）全綠；prod smoke「歌單/馬世芳 歌單/馬世芳 滅火器/空查詢」四 scenario + 422 錯誤 UI 驗證。Bonus 修正 `/events` SearchExecutedPayload.mode 接受 `index`（commit `35e6850`+`d851f15`）。同 session discuss 收斂引用呈現 → propose 兩 parked change。 |
| **2026-05-31** `eval-runner-eval-context-plumbing` ✅ done | `openspec/changes/archive/2026-05-31-eval-runner-eval-context-plumbing/` | 11/11 task done。Runner v2 startup 生 run_id (`eval-YYYYMMDDTHHMMSSZ-<8hex>`) + 每 turn 注入 `X-Eval-Run-Id` / `X-Eval-Item-Id` / `X-Eval-Turn-Idx`；backend `bind_eval_context` FastAPI dependency 在 admin + 三 header 齊 + turn_idx int>=0 → `set_eval_context()`、reset on request end；非 admin / 缺 header / malformed silent skip（不 4xx）。新增 `sql_rca_demo.py`（3 段：per-turn span count / cross-run query diff / per-turn tool timeline）+ `prompt_fingerprint_diff.py --source=sql` 路徑。Phase 5 prod 驗：run `eval-20260530T181920Z-465dd6d2` → 34 span / 8 distinct items / mt03 turn_idx 0,1,2 全 NOT NULL；admin caller 無 X-Eval-* header → eval_traces baseline 不增。**Hotfix 同 change `842d69d`**：span_writer JSONB serialization（asyncpg DataError dormant bug，首次真正 exercise PG sink 才暴露；三欄 `json.dumps + CAST AS JSONB`）。同 session 抓到 prod `EVAL_TRACING_ENABLED=false`（記憶寫 ON 不符）、toggle + redeploy 後生效。完整 case study: `docs/case-studies/eval-runner-eval-context-plumbing-2026-05-31.md` |
| **2026-05-30** `langfuse-sdk-overhead-rca` ✅ spike done | `openspec/changes/archive/2026-05-30-langfuse-sdk-overhead-rca/` | Investigation-only spike。加 per-op timing probe (`EVAL_TRACING_TIMING_PROBE` env)、prod 量測證實 Langfuse Cloud SDK overhead 平均 0.947 ms/span、P95 1.689 ms/span、30 span ~28ms — 4.4 P95 +3.4s attribution 給 SDK 是錯的、是 cross-session noise。Forward decision: CLOSE `langfuse-self-host-evaluation` follow-up。完整 RCA: `docs/case-studies/langfuse-sdk-overhead-rca-2026-05-30.md` |
| **2026-05-30** `eval-framework-upgrade` ✅ PARTIAL ship | `openspec/changes/archive/2026-05-30-eval-framework-upgrade/` | 33/33 task done。Langfuse Cloud Free + PG eval_traces 雙 sink、6 個新 grader (4 DeepEval 內建 + 2 GEval 自寫)、`_calibration_8.json` 8 題 byte-equivalent subset、`retrieve_probe.py` + `prompt_fingerprint_diff.py` 兩 CLI、PR template Retrieval/Prompt checklist、runbook、全 34 baseline。**未達 4.4 acceptance**：prod 灰度 P95 +3375ms FAIL (<100ms gate)、tracing 預設 OFF、open follow-up `langfuse-self-host-evaluation`。4.1 chunk_recall_grouped -0.10 RCA 確認非 regression（agent 落相鄰 chunk、answer 品質完全沒變、`contextual_precision=0.92` 證 retrieval 健康）— 驗證 task 2.3b ContextualRecall grader 加入正當性。完整 case study: `docs/case-studies/eval-framework-upgrade-2026-05-30.md` |
| **2026-05-28** `retrieve-quality-step1-idf-and-prefilter` ❌ FAILED | `openspec/changes/archive/2026-05-28-retrieve-quality-step1-idf-and-prefilter/` | 兩 Layer 全 revert。Layer A IDF-bucketed `ts_rank` chunk_recall 0.482 → 0.382；Layer B chat agent EP-ref dispatch chunk_recall 0.482 → 0.340。Prod 留 orphan `transcript_token_freq` table + alembic migration（無程式引用）。下動 pivot 評估框架升級。完整 RCA: `docs/case-studies/retrieve-quality-step1-idf-and-prefilter-2026-05-28.md` |
| **2026-05-18 batch (3 個)** `backfill-progress-admin-tab` + `whisper-chunking-fix` + `multi-provider-usage-monitoring` | `openspec/changes/archive/2026-05-18-*` | Admin Queue Tab 進度概覽；Whisper 80min 集 multipart 25MiB chunk fix；3 provider 用量監控 + 預算告警（aihub adapter URL 猜錯 follow-up 開 `aihub-graphql-adapter-migration`）。Release log v1.7 |
| **2026-05-17 batch (2 個)** `enumeration-rule-pattern-broaden` + `enumeration-topic-finder-include-title` | `openspec/changes/archive/2026-05-17-*` | Rule pattern 加反序「集數有哪些」+ find_episodes_by_topic 對 LLM phrase 先 jieba 切（CJK simple analyzer bug）；q26 0.333→1.0、aggregate 0.5467→**0.88** |
| **2026-05-16 batch (4 個)** `r3-3-metadata-filter` + `r3-3-chat-enum-grounding` + `chat-input-ime-composition-fix` + `eval-runner-chat-enum-scoring` | `openspec/changes/archive/2026-05-16-*` | R3.3 milestone (v1.7)：guests JSONB + admin tab + title_tsvector + 三池 RRF + LLM entity_extraction + ChatResponse enumeration_episodes + frontend EnumerationSection；chat 答案 grounding + topic-trigger + topic-filter SQL；IME enter 送出 bug；eval runner 對 chat enum 計分。Prod Recall@5 0.86 (n=28)，q25 0.04→0.76、aggregate 0.1867→0.5467。詳見 `docs/case-studies/r33-metadata-filter.md` |
| **R3.5** `r3-5-disable-routing` + R3.4 + R3.2 milestone (6 個) | `openspec/changes/archive/2026-05-13-*` | **v1.7 milestone**：關掉 two-layer routing + 6 個 R3.x changes pair archive。Recall@5 (human-curated) 0.0625 → **0.4375 (7x)**、P95 2170ms |
| `r2-1-citation-infra` + `r2-1-followup-bugs` + `r2-1-prompt-fix` | `openspec/changes/archive/2026-05-10-r2-1-*` | citation infrastructure（v1.6）：search 結果加 highlights / before/after_text / ai_summary 60 字 + 「展開」+「跳到這段內容」button + URL deep-link shareable + LLM prompt 加拒答模式 + citation parser strip [N]。**Faithfulness gate 重訂為軟 gate（≥ 0.50）** |
| `db-backup` | `openspec/changes/archive/2026-05-07-db-backup/` | 每日 03:00 UTC pg_dump → age → R2 離站；月度 GHA 還原驗證；7d/4w/12m retention。月成本 ~$1 |
| `freemium-onboarding` | `openspec/changes/archive/2026-05-04-freemium-onboarding/` | LandingPage + 公開段落搜尋（IP rate limit 20/day）+ 登入解鎖 LLM 答案 + quota 申請流程 |

完整列表（含更早）見 `openspec/changes/archive/` 目錄。

---

## 維護規則

- 本文件與 Claude 的記憶檔案 `project_pending_changes.md` **互為鏡像**，更新時請同步維護兩邊（feedback_roadmap_dual_write）
- 路徑變更 / 新增 / archive 時兩處都要動
- 詳細工作紀錄類文件（case studies / research）放 `docs/case-studies/` + `docs/research/`，**不進 commit**（feedback_case_studies_no_commit）

## 工作紀律（不在路線圖內，但執行時受其約束）

- **成本紀律**：pilot < $20 免問；> $30 大規模回填要 confirm；AI Hub 可程式查餘額（Balance/100k=USD），OpenAI 走 α 方案手動回報（baseline 記在 memory `reference_openai_balance.md`）
- **單節目 pilot 策略**：所有「全 corpus 重做」類動作（re-chunking / re-embed / 換 embedding model）必須先在單一節目（「這又沒有很屌」）pilot 驗證，再 rollout 其他兩個節目
