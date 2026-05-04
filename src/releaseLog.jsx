// Release Log entries — single source of truth for both ReleaseLogPage and PresentationPage.
// Each entry: { date, slug, milestone, tag, title:{zh,en}, summary:{zh,en} }
// Tag → Badge variant (in ReleaseLogPage): feature→success, fix→warning, enhancement→default, ui→muted

// Stats snapshot — manually updated when generating the presentation.
// Numbers from prod backend GET /shows on 2026-05-01.
// transcript_chunks count is estimated (~50 chunks/episode); zeabur-service-exec
// hits Cloudflare 524 timeout so direct DB query was unreliable.
const STATS_AS_OF = '2026-05-03';
const STATS_CHANGES_COUNT = 31;
const STATS_EPISODES_COUNT = 137;        // transcripts.status = 'completed'
const STATS_VECTORS_COUNT = 6850;        // ~estimate: 137 × ~50 chunks/ep

// Tag labels (used by both pages).
const TAG_LABELS = {
  feature:     { zh: '新功能',   en: 'Feature' },
  fix:         { zh: 'Bug 修復', en: 'Fix' },
  enhancement: { zh: '系統優化', en: 'Enhancement' },
  ui:          { zh: '介面調整', en: 'UI' },
};

const MILESTONE_LABELS = {
  'v0.1': { zh: 'v0.1 — RAG MVP 基礎建設',         en: 'v0.1 — RAG MVP Foundation' },
  'v0.2': { zh: 'v0.2 — 後台管理與排程',           en: 'v0.2 — Admin & Schedule' },
  'v0.3': { zh: 'v0.3 — 真實 Cron 與平行轉錄',     en: 'v0.3 — Real Cron & Parallel Queue' },
  'v0.4': { zh: 'v0.4 — 手機版與友善錯誤',         en: 'v0.4 — Mobile & Friendly Errors' },
  'v0.5': { zh: 'v0.5 — 帳號驗證與查詢額度',       en: 'v0.5 — Auth & Query Quota' },
  'v0.6': { zh: 'v0.6 — 部署不中斷正在跑的轉錄',   en: 'v0.6 — Deploys Without Interrupting Transcriptions' },
  'v0.7': { zh: 'v0.7 — AI 設定集中化',            en: 'v0.7 — AI Settings Consolidation' },
  'v0.8': { zh: 'v0.8 — 自動化驗證後門',           en: 'v0.8 — Automated Verification Backdoor' },
  'v0.9': { zh: 'v0.9 — 每集 AI 摘要',             en: 'v0.9 — Per-Episode AI Summary' },
};

// Entries — newest milestone first; within each milestone newest date first.
const RELEASE_LOG = [
  // ─── v0.9 — Per-Episode AI Summary (5/04) — fix ───
  {
    date: '2026-05-04', slug: 'summary-stale-detection', milestone: 'v0.9', tag: 'fix',
    title: {
      zh: '摘要 task 卡住會自動回收',
      en: 'Stuck Summary Tasks Auto-Recover',
    },
    summary: {
      zh: '上週批次補摘要時遇到 3 集卡在「摘要中」一整天沒人救——worker 重啟、Celery task 消失、狀態沒人更新。改進：beat 每分鐘掃描 episodes 表，若摘要狀態 `running` 超過 10 分鐘（預設可由 env 調整），自動重置為 pending 並重新排隊；同時加上 Celery on_failure handler，worker 被 SIGKILL/OOM 殺掉時也會把 row 標為 failed 並寫入錯誤訊息。Admin 後台的摘要徽章 hover 上去現在會顯示具體錯誤訊息，方便排查。資料層加了兩個欄位記錄起跑時間和錯誤字串。一般使用者完全不會察覺，純粹是後台 reliability 補強。',
      en: 'During last week\'s summary backfill, 3 episodes got stuck in "summarising" for a full day — worker restarted, Celery task vanished, nothing updated the row. Fix: beat scans the episodes table every minute and any row whose summary has been "running" longer than 10 min (env-configurable) is reset to pending and re-queued. A Celery on_failure handler also fires when a worker gets SIGKILL\'d (OOM, container restart) and marks the row failed with the exception text. The admin queue badge now reveals the underlying error on hover so debugging is straightforward. Adds two database fields for start-time and error-string tracking. End users see no change — purely an admin reliability improvement.',
    },
  },

  // ─── v0.9 — Per-Episode AI Summary (5/03) ───
  {
    date: '2026-05-03', slug: 'episode-ai-summary', milestone: 'v0.9', tag: 'feature',
    title: {
      zh: '每集自動 AI 摘要',
      en: 'Automatic Per-Episode AI Summary',
    },
    summary: {
      zh: '節目 RSS 描述常常是行銷文案、廣告或來賓 IG，看不出這集到底在講什麼。新增每集自動產出 80-150 字繁中摘要：轉錄完成後鏈式觸發 Celery task，把逐字稿用 tiktoken 切成 12K token 的 chunks，map-reduce 兩階段（先列重點、再總結）由 admin 後台設定的 LLM step (預設 gpt-5-mini) 處理。結果存在 episodes 表新加的欄位（status: pending / running / done / failed），列表 / 查詢面板 / 逐字稿頁三處顯示，失敗對使用者完全透明（自動 fallback 顯示原 RSS 描述，不顯示 spinner / 錯誤訊息）。Admin 在轉錄序列頁多了 summary badge、單集重跑按鈕、以及一鍵「批次補摘要」處理既有 360 集（大約 $0.7 LLM 費用）。',
      en: 'RSS descriptions are often marketing copy or sponsor links — they don\'t tell you what an episode is actually about. Each episode now auto-generates an 80-150 character Traditional Chinese summary: a Celery task chains off transcription completion, chunks the transcript with tiktoken at 12K tokens, then runs a map-reduce (extract bullets → reduce to summary) through whichever LLM step admins configure (default gpt-5-mini). Results live on the episodes table (status enum: pending / running / done / failed) and surface in the episode list, query panel, and transcript header. Failures are transparent — users see the original RSS description with no spinner or error. Admins gain a summary badge in the transcription queue, a single-episode regenerate button, and a one-click backfill for the 360 existing episodes (~$0.7 of LLM spend).',
    },
  },

  // ─── v0.8 — Automated Verification Backdoor (5/03) ───
  {
    date: '2026-05-03', slug: 'e2e-login-backdoor', milestone: 'v0.8', tag: 'enhancement',
    title: {
      zh: 'Claude 自動化驗證的 e2e 登入後門',
      en: 'E2E Login Backdoor for Claude Verification',
    },
    summary: {
      zh: '以前 Claude 用瀏覽器自動化驗證 prod 的時候，得仰賴一份 14 天就過期的 cookie 檔案，每次過期都得開發者手動重抓一次。新增一條受嚴格保護的後門 endpoint：只有設了 E2E_LOGIN_TOKEN 環境變數時才會註冊（沒設的部署連 404 都不會洩漏這條 path 存在），用 HMAC 比對 token 防 timing attack，發出來的 session 強制 15 分鐘過期，IP 連續 5 次失敗會被 60 秒 rate limit。整個流程只發給 ADMIN_EMAILS 第一個 email，所有成功失敗都寫 audit log。一般使用者完全感覺不到這個改動 — 純粹給自動化測試流程用。',
      en: 'Claude\'s browser-automation verification used to rely on a stored cookie file that expired every 14 days, requiring a manual re-login. A tightly-scoped backdoor endpoint is now available: registered ONLY when E2E_LOGIN_TOKEN env is set (deployments without it return 404 indistinguishably from any unmapped path), HMAC token comparison resists timing attacks, issued sessions are capped at 15-minute TTL regardless of normal session config, and an IP gets a 60-second rate-limit after 5 failed attempts. The endpoint always issues a session for ADMIN_EMAILS[0]; every success and failure goes through audit logging. Invisible to end users — purely a verification-pipeline tool.',
    },
  },

  // ─── v0.7 — AI Settings Consolidation (5/03) ───
  {
    date: '2026-05-03', slug: 'admin-llm-step-config', milestone: 'v0.7', tag: 'enhancement',
    title: {
      zh: 'AI 設定集中化（API 金鑰 + 五種處理步驟）',
      en: 'Centralised AI Settings (API Keys + Five Processing Steps)',
    },
    summary: {
      zh: '原本的「LLM 模型設定」只支援回答 + 改寫兩個固定 LLM，金鑰寫死在 env，要切換轉錄供應商還得 redeploy。重構後 admin 後台多了兩張表：API 金鑰可集中管理（自由命名 provider + label，支援 OpenAI / Anthropic / Google / Zeabur AI Hub 預設下拉），以及 5 個 AI 處理步驟（answer / rewrite / summary / embedding / transcription），每個步驟挑一把已建立的金鑰、自選 base_url / model。embedding 步驟強制只能挑 OpenAI 金鑰（因為 Zeabur Hub 不支援 embedding endpoint），改 model 時前端會警告會讓既有向量失效。轉錄步驟可在 OpenAI Whisper API 與本地 faster-whisper 之間切換，無需 redeploy。本變更不直接面對使用者，但鋪好了 v0.8「每集 AI 摘要」要用的 summary step 位子。',
      en: 'The old "LLM Model Settings" only supported two fixed LLMs (answer + rewrite) with the api_key baked into env vars; switching the transcription provider required a redeploy. The admin tab is now backed by two tables: a centralised API Keys registry (free-form provider + label, with OpenAI / Anthropic / Google / Zeabur AI Hub presets) and five AI processing steps (answer / rewrite / summary / embedding / transcription), each picking a key and its own base_url / model. The embedding step enforces an OpenAI-provider key (Zeabur Hub does not proxy /v1/embeddings); changing the embedding model surfaces a warning that existing vectors will need reindexing. Transcription can be switched between OpenAI Whisper API and local faster-whisper from the UI, no redeploy. Not user-facing on its own, but lays the groundwork for v0.8\'s per-episode AI summary feature.',
    },
  },

  // ─── v0.6 — Deploys Without Interrupting Transcriptions (5/03) ───
  {
    date: '2026-05-03', slug: 'deploy-resilience', milestone: 'v0.6', tag: 'fix',
    title: {
      zh: '部署不中斷正在跑的轉錄',
      en: 'Deploys No Longer Interrupt Running Transcriptions',
    },
    summary: {
      zh: '以前每次重新部署，正在跑的轉錄會卡在「進行中」狀態，要等 30 分鐘系統才會自動把它清掉重跑。現在改成 worker 重啟後 1～3 分鐘內就會自動把卡住的集數推回排隊，由新 worker 接手繼續轉。順手修了強制取消的隱藏 bug（某些狀況下排隊額度會卡死）。dispatcher 跟 beat 兩個背景服務也不會再因為缺登入相關設定就啟動失敗。',
      en: 'Previously a redeploy would leave any in-flight transcription stuck in "running" for 30 min before the stale-detection cron would re-queue it. Now stuck rows are pushed back to the pending queue within 1–3 min after a worker restart, so a new worker can pick up where the dead one left off. Also fixed a hidden bug in force-cancel that could leave a transcription throttle slot occupied; and dispatcher/beat services no longer crash on startup when auth-only env vars are unset.',
    },
  },

  // ─── v0.5 — Auth & Query Quota (5/02) ───
  {
    date: '2026-05-02', slug: 'post-auth-ui-and-cleanup', milestone: 'v0.5', tag: 'ui',
    title: {
      zh: '更新日誌時間軸 + 佇列排隊編號 + 清債',
      en: 'Timeline UI + Queue Numbering + Cleanup',
    },
    summary: {
      zh: '更新日誌頁改成單條垂直時間軸（最新在上）；轉錄佇列「進行中」分頁改成 running 在上、pending 帶 1/2/3 排隊編號；空節目時 admin 可一鍵跳後台。後端新增 GET /admin/stats 讓更新日誌的數字即時顯示。順手把 23 個既有 admin pytest 補上 auth fixture。',
      en: 'Release Log redesigned as a vertical timeline (newest first); Transcription Queue active sub-tab puts running rows on top with 1/2/3 position badges on pending; empty PodcastSelect routes admins to admin show management. New GET /admin/stats lets the Release Log show live numbers; 23 admin pytest cases got the missing auth fixture.',
    },
  },
  {
    date: '2026-05-02', slug: 'authentication-system', milestone: 'v0.5', tag: 'feature',
    title: {
      zh: '帳號驗證系統 + 查詢額度',
      en: 'Authentication System + Query Quota',
    },
    summary: {
      zh: '砍掉寫死的 admin 帳密 modal,改成 Google 登入。一般使用者預設 100 次查詢額度,後台可加值;管理員權限只開放給 ADMIN_EMAILS env 白名單裡的 email。所有後台 API 都加 admin gate,跨站請求被 CSRF token + Origin 檢查擋下。',
      en: 'Replaces the hardcoded admin login modal with Google SSO. Members get 100 queries/account by default (admin can top up); admin role auto-granted only for emails in the ADMIN_EMAILS env allowlist. All admin endpoints require admin role; cross-site requests blocked by CSRF token + Origin check.',
    },
  },

  // ─── v0.4 — Mobile & Friendly Errors (5/01, 4/30) ───
  {
    date: '2026-05-01', slug: 'release-log-and-presentation', milestone: 'v0.4', tag: 'feature',
    title: {
      zh: '新增更新日誌 + 簡報頁',
      en: 'Release Log + Presentation Pages',
    },
    summary: {
      zh: '前端加入「更新日誌」分頁,把過去 24 個 archived changes 翻成白話雙語條目按里程碑分組。獨立的 #presentation 簡報頁 13 張 slide 介紹系統演進,可同步產出 .pptx。',
      en: 'Adds a Release Log tab translating 24 historic archived changes into plain bilingual entries grouped by milestone, plus a standalone #presentation deck (13 slides) that can also export as .pptx.',
    },
  },
  {
    date: '2026-05-01', slug: 'responsive-mobile-layout', milestone: 'v0.4', tag: 'ui',
    title: {
      zh: '全站支援手機版 RWD',
      en: 'Full Mobile Responsive Support',
    },
    summary: {
      zh: '加入 768px 兩段斷點,手機版改成漢堡選單、單欄表單、抽屜式集數面板,後台佇列拖曳排序改用上下箭頭按鈕。',
      en: 'Two-tier breakpoint at 768px: hamburger menu, single-column forms, drawer episode panel; queue reorder uses up/down buttons on mobile.',
    },
  },
  {
    date: '2026-05-01', slug: 'friendly-external-api-errors', milestone: 'v0.4', tag: 'enhancement',
    title: {
      zh: '外部 API 錯誤訊息友善化',
      en: 'Friendly External API Error Messages',
    },
    summary: {
      zh: 'OpenAI / Zeabur AI Hub 失敗時不再顯示「Failed to fetch」,改成「Zeabur AI Hub 配額不足,請檢查餘額」這類具體中文訊息,並修正 CORS 在 unhandled exception 下的 header 漏寫。',
      en: 'No more "Failed to fetch" — surfaces specific localized messages like "Zeabur AI Hub quota exceeded". Also fixes missing CORS headers on unhandled exceptions.',
    },
  },
  {
    date: '2026-04-30', slug: 'queue-tabs-and-schedule-cleanup', milestone: 'v0.4', tag: 'ui',
    title: {
      zh: '轉錄佇列改子分頁、排程支援週幾選擇',
      en: 'Queue Sub-tabs & Weekday Picker',
    },
    summary: {
      zh: '佇列頁面切成「排隊中+執行中 / 完成 / 失敗+取消」三個子分頁。排程下拉砍掉 hourly,週排程可選星期幾,modal 動態顯示「每週X 09:30 觸發」。',
      en: 'Queue split into three sub-tabs (active / done / closed). Schedule dropdown drops hourly; weekly schedules now pick a day-of-week with a live preview hint.',
    },
  },

  // ─── v0.3 — Real Cron & Parallel Queue (4/28) ───
  {
    date: '2026-04-28', slug: 'transcription-queue-and-schedule-ui', milestone: 'v0.3', tag: 'ui',
    title: {
      zh: '後台新增「轉錄序列」管理頁',
      en: 'Transcription Queue Admin Page',
    },
    summary: {
      zh: '後台多一個分頁可看每筆轉錄任務的狀態,支援取消 / 強制取消 / 重試 / 忽略,並可拖曳調整排隊順序、設定平行上限。',
      en: 'New admin tab listing every queue row by status; supports cancel, force-cancel, retry, ignore, drag-reorder, and concurrency cap input.',
    },
  },
  {
    date: '2026-04-28', slug: 'stale-running-detection', milestone: 'v0.3', tag: 'fix',
    title: {
      zh: '自動偵測並回收卡死的轉錄任務',
      en: 'Auto-Recover Stale Running Tasks',
    },
    summary: {
      zh: 'Worker 重新部署時若有 task 訊息遺失,佇列會永遠卡在 running。新增每分鐘掃描,執行超過 30 分鐘且 worker 沒在跑的 row 自動標 failed 並釋放槽位。',
      en: 'Worker redeploys could lose task messages and freeze the queue. A per-minute sweep marks rows running > 30min without a live worker as failed and frees the slot.',
    },
  },
  {
    date: '2026-04-28', slug: 'parallel-transcription-and-force-cancel', milestone: 'v0.3', tag: 'enhancement',
    title: {
      zh: '平行轉錄 3 集 + 強制取消',
      en: 'Parallel Transcription (×3) + Force Cancel',
    },
    summary: {
      zh: 'Worker 升為 concurrency=3 達成真平行;新增「強制取消」可中止已啟動的轉錄任務。',
      en: 'Worker now runs concurrency=3 for true parallelism; force-cancel can terminate running transcriptions.',
    },
  },
  {
    date: '2026-04-28', slug: 'db-driven-queue-and-real-cron', milestone: 'v0.3', tag: 'feature',
    title: {
      zh: '排程真的會自動跑了',
      en: 'Schedules Now Actually Run Automatically',
    },
    summary: {
      zh: '排程設定從「死資料」變成真正的 cron:Celery Beat 每分鐘掃排程表,到時間自動拉新集數入隊。佇列改由 DB 表驅動,所有操作可原子化記錄。',
      en: 'Schedules transition from static config to real cron: Celery Beat scans the table every minute, pulls new episodes, and enqueues them. Queue is now DB-driven for atomic operations.',
    },
  },

  // ─── v0.2 — Admin & Schedule (4/24–4/27) ───
  {
    date: '2026-04-27', slug: 'transcription-progress-visibility', milestone: 'v0.2', tag: 'feature',
    title: {
      zh: '轉錄進度與外部 API 健康狀態可視化',
      en: 'Transcription Progress & API Health Dashboard',
    },
    summary: {
      zh: '排程頁卡片可展開看每集 pending/processing/completed/failed 數;新增「外部 API 狀態」分頁顯示 OpenAI Whisper/Chat/Embedding 三者最近呼叫狀態與錯誤分類。',
      en: 'Expandable per-show progress (pending/processing/completed/failed); new "External API Status" tab tracks OpenAI Whisper / Chat / Embedding health with categorized errors.',
    },
  },
  {
    date: '2026-04-27', slug: 'remove-admin-login-demo-hint', milestone: 'v0.2', tag: 'ui',
    title: {
      zh: '移除登入視窗的示範帳密提示',
      en: 'Remove Demo Credentials Hint',
    },
    summary: {
      zh: '原本登入框直接顯示示範帳密提示,邀請外部試用前先把這行拿掉,避免影響「未授權使用者」測試體驗,也避免帳密外流。',
      en: 'Removed the demo-credential hint from the login modal so external testers experience the unauthorized-user flow naturally — and credentials no longer leak via the UI.',
    },
  },
  {
    date: '2026-04-26', slug: 'fix-rss-200-cap', milestone: 'v0.2', tag: 'fix',
    title: {
      zh: '修正 RSS 抓集數上限被寫死 200 集',
      en: 'Fix RSS 200-Episode Cap',
    },
    summary: {
      zh: '抓 RSS 時硬寫死「最多 200 集」,壹加壹電台真實有 251 集,DB 卻只有 200 集。改成預設不截斷,使用者按「更新節目集數」就會補回缺失的集數。',
      en: 'RSS parser hard-coded a 200-episode cap, dropping 51 episodes from a 251-episode feed. Default removed; clicking "Update episodes" backfills the missing entries.',
    },
  },
  {
    date: '2026-04-25', slug: 'schedule-editing-and-run-now', milestone: 'v0.2', tag: 'feature',
    title: {
      zh: '排程可編輯、單節目可立刻執行',
      en: 'Editable Schedules & Run-Now Per Show',
    },
    summary: {
      zh: '排程不再只能刪除重建,新增「編輯」modal 可改頻率/時間/Whisper 模型/上限。新增「立刻執行」按鈕,只轉最新 N 集而非全部。',
      en: 'Schedules now have an Edit modal (frequency / time / model / cap) and a per-show Run-Now button that transcribes only the latest N episodes instead of the full backlog.',
    },
  },
  {
    date: '2026-04-25', slug: 'redesign-schedule-tab-actions', milestone: 'v0.2', tag: 'ui',
    title: {
      zh: '排程頁拿掉容易誤解的「同步」字眼',
      en: 'Redesign Schedule Tab Actions',
    },
    summary: {
      zh: '「同步集數」(只抓 RSS)和「同步所有」(會燒 OpenAI 額度)語意混在一起。改名為「更新節目集數」/「轉錄未完成集數」並加入 Gmail 風 checkbox 批次選取,批次轉錄前跳一次確認。',
      en: '"Sync" was overloaded — covering both RSS-only refresh and OpenAI-spending batch jobs. Renamed to clearer verbs, added Gmail-style checkbox selection, and a confirm before batch transcription.',
    },
  },
  {
    date: '2026-04-25', slug: 'concurrency-control-and-retry', milestone: 'v0.2', tag: 'enhancement',
    title: {
      zh: '轉錄任務自動重試 + 全域並發限制',
      en: 'Auto-Retry & Global Concurrency Cap',
    },
    summary: {
      zh: 'OpenAI 5xx / 網路中斷 / rate limit 等暫時錯誤改自動重試 3 次(10s→60s→300s 退避)。新增 Redis-based 全域並發限制,避免「同步所有」一次塞爆 worker。',
      en: 'Transient errors (5xx, rate limit, timeouts) now auto-retry 3× with exponential backoff. Redis-based global concurrency cap prevents "sync all" from overloading the worker.',
    },
  },
  {
    date: '2026-04-24', slug: 'transcription-schedule-api', milestone: 'v0.2', tag: 'feature',
    title: {
      zh: '排程設定接上真實後端',
      en: 'Schedule Settings Persisted to Backend',
    },
    summary: {
      zh: '原本後台排程頁是 mock,重整就消失。改成真實 API 持久化每個節目的排程設定(頻率、時間、Whisper 模型、上限)。',
      en: 'Schedule settings (frequency, time, Whisper model, max episodes) are now persisted via real APIs instead of evaporating on refresh.',
    },
  },
  {
    date: '2026-04-24', slug: 'query-ux-improvements', milestone: 'v0.2', tag: 'enhancement',
    title: {
      zh: '查詢頁體驗優化:真實集數列表 + 引用精確化',
      en: 'Query UX Polish: Real Episodes & Precise Citations',
    },
    summary: {
      zh: '右側集數列表接上真實 API。RAG 回答改用結構化輸出,只顯示實際被引用的片段;點擊引用 Badge 跳到逐字稿並高亮對應時間段。',
      en: 'Episode panel now shows real episodes. RAG responses use structured output to surface only actually-cited chunks; clicking a citation jumps to the transcript and highlights the timestamp.',
    },
  },
  {
    date: '2026-04-24', slug: 'fix-split-audio-memory', milestone: 'v0.2', tag: 'fix',
    title: {
      zh: '修正轉錄長集時 worker 記憶體爆掉',
      en: 'Fix OOM When Transcribing Long Episodes',
    },
    summary: {
      zh: '轉錄超過 1 小時的 podcast 時記憶體飆到 1.5–2 GB,觸發 OOM 重啟。改用 ffmpeg stream copy 切段,記憶體常數,Zeabur 4GB plan 穩定運行。',
      en: 'Long podcasts spiked memory to 1.5–2 GB, OOM-killing the worker. Switched to ffmpeg stream-copy chunking — constant memory, stable on Zeabur 4GB plan.',
    },
  },
  {
    date: '2026-04-24', slug: 'admin-show-crud-ui', milestone: 'v0.2', tag: 'feature',
    title: {
      zh: '後台節目管理:刪除 / 同步集數 / 移除排程',
      en: 'Admin Show CRUD: Delete / Sync / Unschedule',
    },
    summary: {
      zh: '後台排程頁每張卡片加入操作按鈕(刪除節目、同步新集數、移除排程),刪除前跳確認 modal,避免誤觸 cascade 刪光所有逐字稿。',
      en: 'Each show card in admin gets action buttons (delete, sync episodes, unschedule). Delete shows a confirm modal to prevent accidental cascade-deletion of transcripts.',
    },
  },

  // ─── v0.1 — RAG MVP Foundation (4/19–4/23) ───
  {
    date: '2026-04-23', slug: 'shows-list-backend', milestone: 'v0.1', tag: 'enhancement',
    title: {
      zh: '節目選擇頁接上真實後端',
      en: 'Shows List Wired to Backend',
    },
    summary: {
      zh: '首頁從 4 個寫死的 mock shows 改成 GET /shows 真實資料,顯示每個節目已轉錄集數的進度條,並補上 loading/error/empty 三種狀態。',
      en: 'Home page swaps 4 hardcoded mock shows for live GET /shows data, with per-show transcribed-count progress bars and loading / error / empty states.',
    },
  },
  {
    date: '2026-04-23', slug: 'rag-query', milestone: 'v0.1', tag: 'feature',
    title: {
      zh: 'RAG 對話查詢上線',
      en: 'RAG Conversational Query Launches',
    },
    summary: {
      zh: '逐字稿切 chunk → embedding → pgvector 檢索 → LLM 帶引用回答。支援多輪對話(前端 5 輪滑動視窗)、Search 模式直接回原文,後台可換 Answer / Rewrite 模型。',
      en: 'Transcripts chunked → embedded → pgvector retrieval → LLM answer with citations. Multi-turn (5-window front-end memory), search-mode raw chunks, swappable Answer/Rewrite models in admin.',
    },
  },
  {
    date: '2026-04-22', slug: 'openai-audio-chunking', milestone: 'v0.1', tag: 'enhancement',
    title: {
      zh: 'OpenAI Whisper 自動切段(突破 25MB 限制)',
      en: 'OpenAI Whisper Auto-Chunking (Bypass 25MB Limit)',
    },
    summary: {
      zh: 'OpenAI Whisper API 限單檔 25MB,長 podcast 會被拒。改成超過閾值自動切段、分批呼叫、合併結果並調整時間軸,使用者完全無感。',
      en: 'OpenAI Whisper rejects files >25MB. Provider now auto-chunks long audio, batches uploads, and merges results with corrected timestamps — transparent to the user.',
    },
  },
  {
    date: '2026-04-21', slug: 'transcription-pipeline', milestone: 'v0.1', tag: 'feature',
    title: {
      zh: '語音轉錄 Pipeline(Whisper + 任務佇列)',
      en: 'Transcription Pipeline (Whisper + Task Queue)',
    },
    summary: {
      zh: '集數音檔下載到 R2 物件儲存後,Celery worker 呼叫 Whisper(OpenAI 或本機 faster-whisper)轉成帶時間戳的逐字稿。新增 transcribe / get-transcript / batch transcribe API。',
      en: 'Audio files land in R2; Celery workers run Whisper (OpenAI or local faster-whisper) to produce timestamped transcripts. Adds transcribe / get-transcript / batch-transcribe APIs.',
    },
  },
  {
    date: '2026-04-21', slug: 'rss-feed', milestone: 'v0.1', tag: 'feature',
    title: {
      zh: 'RSS Feed 解析 + 節目管理 API',
      en: 'RSS Feed Parser + Shows API',
    },
    summary: {
      zh: '使用者可貼 RSS URL 匯入真實節目,系統解析 RSS 2.0 + iTunes 延伸欄位,寫入 shows 與 episodes 表。新增 CRUD / sync / list 一整組節目 API。',
      en: 'Paste an RSS URL to import a real podcast — parses RSS 2.0 + iTunes fields into shows / episodes tables. Full CRUD + sync + list APIs included.',
    },
  },
  {
    date: '2026-04-21', slug: 'backend-api', milestone: 'v0.1', tag: 'feature',
    title: {
      zh: '後端骨架建立(FastAPI + PostgreSQL + pgvector)',
      en: 'Backend Skeleton (FastAPI + PostgreSQL + pgvector)',
    },
    summary: {
      zh: '建立 FastAPI 應用結構、PostgreSQL schema(節目/集數/逐字稿/向量)、pgvector extension、Alembic migration、health check,作為後續所有功能的基礎。',
      en: 'Establishes FastAPI structure, PostgreSQL schema (shows / episodes / transcripts / vectors), pgvector extension, Alembic migrations, and health-check — foundation for all features.',
    },
  },
  {
    date: '2026-04-19', slug: 'architecture-decisions', milestone: 'v0.1', tag: 'enhancement',
    title: {
      zh: '專案架構決策(技術棧定錨)',
      en: 'Architecture Decisions (Tech Stack Anchored)',
    },
    summary: {
      zh: '確立技術棧:前端 React CDN、後端 FastAPI、資料庫 PostgreSQL+pgvector、儲存 Cloudflare R2、部署 Zeabur。後續所有開發以此為錨。',
      en: 'Tech stack anchored: React CDN frontend, FastAPI backend, PostgreSQL + pgvector, Cloudflare R2 storage, Zeabur deployment. All subsequent work builds on this.',
    },
  },
];

Object.assign(window, {
  RELEASE_LOG,
  STATS_AS_OF,
  STATS_CHANGES_COUNT,
  STATS_EPISODES_COUNT,
  STATS_VECTORS_COUNT,
  TAG_LABELS,
  MILESTONE_LABELS,
});
