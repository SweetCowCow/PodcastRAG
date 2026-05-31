// Release Log entries — single source of truth for both ReleaseLogPage and PresentationPage.
// Each entry: {
//   date, slug, milestone, tag,
//   title:{zh,en},
//   summary:{zh,en},
//   summaryBullets?: { zh: string[], en: string[] },  // optional, 2–4 short bullets per language
// }
// Tag → Badge variant (in ReleaseLogPage): feature→success, fix→warning, enhancement→default, ui→muted

// Stats snapshot — manually updated when generating the presentation.
// Numbers from prod backend GET /shows on 2026-05-01.
// transcript_chunks count is estimated (~50 chunks/episode); zeabur-service-exec
// hits Cloudflare 524 timeout so direct DB query was unreliable.
// These are fallbacks only — pages now live-fetch from GET /stats (public).
// Numbers updated 2026-05-04 to current rough magnitude so the fallback isn't
// dramatically off when the API call fails.
const STATS_AS_OF = '2026-05-04';
const STATS_CHANGES_COUNT = 35;
const STATS_EPISODES_COUNT = 247;        // transcripts.status = 'completed'
const STATS_VECTORS_COUNT = 113000;      // transcript_chunks rows

// Tag labels (used by both pages).
const TAG_LABELS = {
  feature:     { zh: '新功能',         en: 'Feature' },
  fix:         { zh: 'Bug 修復',       en: 'Fix' },
  enhancement: { zh: '系統優化',       en: 'Enhancement' },
  ui:          { zh: '介面調整',       en: 'UI' },
  experiment:  { zh: '實驗（未上線）', en: 'Experiment (Not Shipped)' },
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
  'v1.0': { zh: 'v1.0 — 公開上線：freemium 模式',   en: 'v1.0 — Public Launch: Freemium Mode' },
  'v1.1': { zh: 'v1.1 — 收集回答品質回饋',         en: 'v1.1 — Collecting Answer Quality Feedback' },
  'v1.2': { zh: 'v1.2 — 量化 RAG 答題準確度基線',  en: 'v1.2 — RAG Accuracy Baseline, Measured' },
  'v1.3': { zh: 'v1.3 — 把資料背在保險上',         en: 'v1.3 — Putting Your Data on Insurance' },
  'v1.4': { zh: 'v1.4 — 混合檢索：找到節目主寫的關鍵字', en: 'v1.4 — Hybrid Retrieval: Catching the Host\'s Own Keywords' },
  'v1.5': { zh: 'v1.5 — 更新日誌變好讀',           en: 'v1.5 — Release Log, Browsable' },
  'v1.6': { zh: 'v1.6 — 搜尋結果看得更清楚',       en: 'v1.6 — Search Results, Now Readable' },
  'v1.7': { zh: 'v1.7 — 搜尋準度大幅提升',         en: 'v1.7 — Retrieval Quality, Materially Better' },
  'v1.8': { zh: 'v1.8 — 對話模式 agent 化',         en: 'v1.8 — Chat Mode, Now Agentic' },
  'v1.9': { zh: 'v1.9 — 索引模式：多關鍵字精準搜尋', en: 'v1.9 — Index Mode: Precise Multi-Keyword Search' },
  'v2.0': { zh: 'v2.0 — 查詢體驗統一：一致引用卡 + 引導範例', en: 'v2.0 — Unified Query Experience: Consistent Citations + Guided Examples' },
};

// Entries — newest milestone first; within each milestone newest date first.
const RELEASE_LOG = [
  // ─── v2.0 — Unified Query Experience (5/31) ───
  {
    date: '2026-05-31', slug: 'unified-segment-citation-card', milestone: 'v2.0', tag: 'ui',
    title: {
      zh: '三種搜尋模式的引用卡長相統一了 — 每段都能單獨試聽、或跳到逐字稿看上下文',
      en: 'Citation Cards Unified Across All Three Modes — Each Clip Now Plays In Place or Jumps to the Transcript',
    },
    summary: {
      zh: '在這版之前，同樣一段「引用」在索引、語意、對話三個模式長得完全不一樣：索引是一種卡、語意和對話是另一種卡、列舉題（「歌單哪幾集」）甚至只給集名沒有片段。而且每張卡只有一顆按鈕、把「試聽」跟「跳到逐字稿」綁在一起——你想原地聽一下，結果整頁跳走了。這版把三個模式的引用卡收斂成同一種「片段卡」，外觀與行為一致：每張卡都顯示片段文字（關鍵字高亮）+ 集標題 + 時間戳，並把動作拆成兩顆獨立按鈕——「播放此段」在原地用底部播放器試聽、頁面不跳走；「跳到逐字稿」才導航過去看完整上下文。高亮也統一：索引模式多關鍵字用兩色區分（橘色實線 / 青色虛線，色盲也能靠線型分辨），語意/對話用單色。列舉題現在保留「集清單」之餘，每集還能就地「展開查看各段」、不離頁看到該集的命中片段。另外對話的引用數量不再被檢索深度灌爆——每集最多先顯示 5 段、其餘用「顯示更多」漸進載入，只列出答案真正引用到的段落。',
      en: 'Before this release, the same "citation" looked completely different across the Index, Semantic, and Chat modes — Index had one card style, Semantic/Chat another, and enumeration answers ("which episodes are playlists") gave only episode names with no clips. Worse, each card had a single button that fused "preview" with "jump to transcript" — try to listen in place and the whole page navigated away. This release unifies all three modes onto one shared "segment card" with consistent look and behavior: every card shows the clip text (keyword-highlighted) + episode title + timestamp, with two SEPARATE buttons — "Play" previews in the sticky player WITHOUT leaving the page, and "Jump to transcript" navigates over for full context. Highlighting is unified too: Index multi-keyword search uses a two-color rotation (orange solid / cyan dashed — distinguishable by line style for color-blind users), Semantic/Chat use single color. Enumeration answers now keep the episode list AND let each episode expand its matching clips in place without navigating. Chat citation counts are no longer flooded by retrieval depth — each episode shows at most 5 clips first with a "Show more" to load the rest, displaying only the clips the answer actually cited.',
    },
    summaryBullets: {
      zh: [
        '索引／語意／對話三模式的引用卡收斂成同一種「片段卡」，外觀行為一致',
        '「播放此段」（原地試聽不跳頁）與「跳到逐字稿」（看上下文）拆成兩顆獨立按鈕',
        '高亮統一：索引多關鍵字兩色（橘實線/青虛線，色盲可辨）、語意/對話單色',
        '列舉題保留集清單 + 每集可就地「展開查看各段」不離頁',
        '對話引用每集先顯示 5 段 + 「顯示更多」，只列答案真正引用的段落（與檢索深度解耦）',
      ],
      en: [
        'Index / Semantic / Chat citations unified onto one shared segment card with consistent look + behavior',
        '"Play" (preview in place, no navigation) split from "Jump to transcript" (view context) into two separate buttons',
        'Unified highlighting: Index two-color (orange solid / cyan dashed, color-blind safe), Semantic/Chat single color',
        'Enumeration answers keep the episode list + each episode expands its matching clips in place',
        'Chat shows 5 clips per episode + "Show more", listing only the clips the answer cited (decoupled from retrieval depth)',
      ],
    },
  },
  {
    date: '2026-05-31', slug: 'per-show-mode-example-prompts', milestone: 'v2.0', tag: 'feature',
    title: {
      zh: '新節目沒人搜過也有引導 — 每個模式給你「這個節目」可以怎麼問的範例',
      en: 'Guidance Even for Brand-New Shows — Each Mode Now Suggests Example Questions Tailored to That Show',
    },
    summary: {
      zh: '查詢頁三個模式的輸入框過去只有通用提示，新使用者進到一個節目常常不知道「針對這個節目」可以問什麼。原本有「7 日熱搜」chip 引導，但剛上架或冷門的節目沒有足夠搜尋紀錄，引導就消失了。這版補上兩層引導：(1) 三個模式的輸入框各有一句符合該模式的提示語（索引引導你打關鍵字、語意引導你描述、對話引導你問需要跨集統整的問題）；(2) 輸入框上方的 chip：熱搜夠多就顯示熱搜，**冷啟動時改顯示「範例」chip** —— 這些範例是後端用該節目已有的每集摘要、來賓名單等素材，請 LLM 為每個模式各預先生成 2–3 題「這個節目風格」的問題（譬如索引給「阿嬤家」這種關鍵字、對話給「整理不同來賓對 Diss Track 的看法」這種統整題）。點任何一顆 chip 就自動帶入並執行查詢。範例是「事先產好存起來」的，不會在你每次查詢時即時生成、不增加查詢延遲與成本；新節目轉錄+摘要跑完會自動產生，後台也能一鍵補產。',
      en: 'The three query-mode inputs previously had only generic placeholders, so new users landing on a show often did not know what they could ask "about this show". Trending-query chips helped, but freshly-added or low-traffic shows lack enough search history, so the guidance vanished. This release adds two layers of guidance: (1) each mode\'s input has a mode-specific placeholder (Index nudges you toward keywords, Semantic toward a description, Chat toward cross-episode synthesis questions); (2) the chip row above the input: when trending is plentiful it shows trending, but on cold-start it shows "Example" chips instead — pre-generated by the backend, which feeds each show\'s existing per-episode summaries + guest lists to an LLM to produce 2–3 mode-appropriate example questions per mode (e.g. Index gets keyword entities like "阿嬤家", Chat gets synthesis questions like "compare what different guests think about Diss Tracks"). Clicking any chip populates and runs the query. Examples are pre-generated and cached — never produced live during your query, so no added latency or cost; they generate automatically after a new show finishes transcription + summaries, and admins can backfill on demand.',
    },
    summaryBullets: {
      zh: [
        '三模式輸入框各有符合該模式的提示語（索引=關鍵字、語意=描述、對話=跨集統整）',
        '冷啟動節目（熱搜不足）顯示 LLM 預產的「範例」chip，點擊帶入並執行',
        '範例用該節目的每集摘要 + 來賓名單當素材、為每模式各產 2–3 題該節目風格問題',
        '預產 + 快取，不在查詢時即時生成（零延遲/成本）；轉錄摘要完成自動產 + 後台可一鍵補',
        '上線後三個收錄節目皆已補齊範例（各模式 3 題）',
      ],
      en: [
        'Each mode\'s input has a mode-specific placeholder (Index = keywords, Semantic = description, Chat = cross-episode synthesis)',
        'Cold-start shows (sparse trending) show LLM-pre-generated "Example" chips; clicking populates + runs',
        'Examples use the show\'s per-episode summaries + guest lists, generating 2–3 show-styled questions per mode',
        'Pre-generated + cached, never live at query time (zero latency/cost); auto-generates after summaries finish + admin backfill',
        'All three catalogued shows backfilled at launch (3 examples per mode)',
      ],
    },
  },
  // ─── v1.9 — Index Mode: Precise Multi-Keyword Search (5/31) ───
  {
    date: '2026-05-31', slug: 'keyword-index-mode', milestone: 'v1.9', tag: 'feature',
    title: {
      zh: '第三種搜尋模式「索引」上線 — 多關鍵字精準比對',
      en: 'Third Search Mode "Index" Is Live — Precise Multi-Keyword Matching',
    },
    summary: {
      zh: '查詢頁三個 tab 裡的「索引」過去是「即將推出」佔位，這版正式接通 — 你現在可以一次打多個關鍵字（譬如「馬世芳 歌單」），系統用「嚴格比對」找出真的同時講到這些詞的內容，跟另外兩個模式定位完全不同：「語意」是找意思相近（就算用詞不一樣也撈得到）、「對話」是問一個問題請 AI 整理答案，而「索引」就像對整個節目下 Ctrl+F、要求每個關鍵字都要命中。結果分三層、由準到寬呈現：第一層是「同一段話裡同時出現所有關鍵字」（最精準）；第二層是「同一集裡這些詞分散在不同段落／標題／簡介」（同集相關但不在同一句）；只有當前兩層都掛蛋時，第三層才退而求其次列出「任一關鍵字命中」的結果，避免你看到一片空白。每個關鍵字在結果裡用兩種顏色高亮區分（橘色實線＝逐字稿命中、青色虛線＝標題／簡介命中），第二層的每一集還能就地展開看到實際命中的各個段落，不用跳頁。單次最多回 100 筆、5 秒逾時保護。上線前在 prod 跑四個情境驗證全綠：「歌單」單詞（第一層滿載 100 筆＋第二層 56 集折疊＋分頁）、「馬世芳 歌單」（第二層就地展開 26 段、兩色高亮都對）、「馬世芳 滅火器」（前兩層 0 命中、正確退到第三層 — 也順帶暴露「滅火器」被 Whisper 聽成錯字、逐字稿裡根本沒這三個字，屬已知的 ASR 錯字 backlog）、空查詢（空狀態正確）。另外修掉一個剛接通就會踩到的小 bug：每次用索引搜尋，後端記錄搜尋事件的 API 都會回 422 錯誤（它的合法模式清單沒加進新的 index），現在補上了。',
      en: 'The "Index" tab in the query page — previously a "coming soon" placeholder — is now fully wired up. You can type multiple keywords at once (e.g. "馬世芳 歌單") and the system finds content that genuinely mentions all of them, using strict matching. This positions it distinctly from the other two modes: "Semantic" finds meaning-similar content (even with different wording), "Chat" answers a question via the AI, and "Index" is like running Ctrl+F across the entire show, requiring every keyword to hit. Results come in three tiers, precise to loose: Tier 1 is "all keywords appear in the same passage" (most precise); Tier 2 is "the keywords are spread across different segments / title / description within the same episode" (same-episode relevant but not in one sentence); only when both Tiers 1 and 2 come back empty does Tier 3 fall back to listing "any keyword matches" so you never face a blank screen. Each keyword is highlighted in two colors (orange solid = transcript hit, cyan dashed = title/description hit), and every Tier 2 episode can be expanded in place to see the actual matching segments without navigating away. Capped at 100 results per search with a 5-second timeout. Four prod scenarios verified green before launch: single word "歌單" (Tier 1 maxed at 100 + Tier 2 with 56 episodes collapsed + pagination), "馬世芳 歌單" (Tier 2 inline-expanded 26 segments, both highlight colors correct), "馬世芳 滅火器" (0 hits in Tiers 1-2, correctly fell back to Tier 3 — incidentally exposing that "滅火器" was misheard by Whisper as a typo and the three characters appear nowhere in the transcript, a known ASR-typo backlog item), and an empty query (correct empty state). Also fixed a small bug that fired the moment the feature went live: every index search made the backend\'s search-event-logging API return a 422 error (its list of valid modes had not been updated to include the new "index" mode) — now patched.',
    },
    summaryBullets: {
      zh: [
        '第三種搜尋模式「索引」上線，與「語意」「對話」三模式到齊',
        '一次打多個關鍵字、嚴格比對（每個詞都要命中），像對整個節目下 Ctrl+F — 跟語意（意思相近）、對話（問 AI）定位不同',
        '結果由準到寬分三層：同段全中／同集分散／任一詞命中（僅前兩層皆空才退此層）',
        '關鍵字兩色高亮（橘＝逐字稿、青＝標題／簡介）＋ 第二層可就地展開看實際命中段落',
        '上線前 prod 四情境驗證全綠；煙霧測試順帶再現「滅火器」Whisper ASR 錯字（已知 backlog）。另修掉每次索引搜尋都噴的 422 事件記錄 bug',
      ],
      en: [
        'Index mode is now live — the third and final search mode joins Semantic and Chat',
        'Type multiple keywords with strict AND matching (every word must hit), like Ctrl+F across the whole show — distinct from Semantic (meaning-similar) and Chat (ask the AI)',
        'Three-tier results, precise to loose: same-passage / same-episode-scattered / any-keyword fallback (only when the first two are empty)',
        'Two-color keyword highlighting (orange = transcript, cyan = title/description) + expand-in-place to see Tier 2 matching segments',
        'Four prod scenarios verified green; smoke test incidentally re-surfaced the "滅火器" Whisper ASR-typo (known backlog). Also fixed a 422 on the search-event API that fired on every index search',
      ],
    },
  },
  // ─── v1.8 — Chat Mode: Agentic (5/21~) ───
  {
    date: '2026-05-31', slug: 'eval-runner-eval-context-plumbing', milestone: 'v1.8', tag: 'enhancement',
    title: {
      zh: '評分跑分把「哪一題」「第幾輪」一路標記到資料庫 — RCA 一句 SQL 就能撈',
      en: 'Eval Runs Now Tag Every Trace With Item + Turn — RCA Is One SQL Query Away',
    },
    summary: {
      zh: '昨天的評分框架升級把觀察工具裝起來、把資料庫雙寫倉也建好了，但「評分跑分時把每個 LLM 呼叫 / 工具呼叫貼上題號跟輪次」這條最後一段沒通 — 結果是雙寫倉裡題號欄位全部空白、跨輪比對 RCA 沒法做。這次補完那段，使用者體感沒變化，但未來任何對話品質改動的事後 RCA 時間從「翻 log 拼湊一兩小時」變成「一句 SQL 撈出全部」。具體做法：跑分腳本每次出題前自己生一個 run_id（時間戳 + 隨機字尾）、每送一題就在 HTTP 標頭塞三個欄位（run_id / 題號 / 第幾輪）。後端只在管理員身分 + 三欄齊全時才把這些上下文綁進當下這個 request、結束就回 None；外部使用者完全不會誤觸發、資料庫不會被污染。實作過程踩到兩個 surprise：(1) 雙寫倉的 JSONB 欄位之前沒人真的寫進去，本次第一次跑就被資料庫拒收（驅動程式不認 Python dict、要先轉 JSON 字串再 CAST）— hotfix 修掉、現在每筆乾淨落地。(2) 線上環境本來以為 trace 是開的、實際還是關的 — 切開後再跑才看到 34 個 span 全部落到資料庫、8 個題目 + 多輪題 mt03 三輪全部都有。也附了一個示範腳本，未來任何「為什麼這版退步了」的 RCA，直接拿 SQL 比對兩個 run_id 的 search query 就能看出 agent 是不是改了措辭。',
      en: 'Yesterday\'s eval framework upgrade installed the observability tooling and the dual-sink data warehouse, but the last mile — tagging every LLM/tool call within an eval run with its item id and turn index — was never wired up. Result: locator columns in the warehouse were empty, cross-run RCA SQL was impossible. This change closes that gap. No user-facing change, but post-hoc RCA for any chat-quality regression now drops from "1-2 hours scraping logs" to "one SQL query". How: the eval runner generates a run_id (timestamp + random suffix) per invocation and attaches three headers per request (run_id / item_id / turn_idx). Backend honors them only when the caller is an admin AND all three headers are present; prod user traffic is silently ignored, the warehouse stays clean. Two surprises along the way: (1) the warehouse\'s JSONB columns had never actually been written to before — the asyncpg driver rejected Python dicts on first real INSERT (needed JSON serialization + explicit CAST). Hotfix in same commit, now every span lands cleanly. (2) Tracing was assumed ON in prod but was actually OFF; after toggling, 34 spans landed for the calibration run (8 distinct items + multi-turn mt03 across 3 turns). A demo SQL script ships alongside, so future "why did this version regress?" questions can be answered by SQL-diffing the agent\'s search queries between two run_ids.',
    },
    summaryBullets: {
      zh: [
        '評分跑分時的每個 LLM/工具呼叫，現在都帶有 run_id / 題號 / 輪次 三個欄位落到資料庫',
        '未來 RCA「為什麼這版退步？」一句 SQL 就能比兩版 agent search query 差異',
        '只認管理員身分 + 三欄齊全才綁定 — 外部使用者流量不會誤污染資料倉',
        '過程踩到兩個 surprise：JSONB 寫入機制壞著（hotfix 修掉）+ trace 線上其實是關的（已開）',
        '本次跑完驗證：8 題 calibration + 多輪題 mt03 三輪 共 34 個 span 全部乾淨落地',
      ],
      en: [
        'Every LLM/tool call in an eval run now carries run_id / item_id / turn_idx in the warehouse',
        'Future "why did this version regress?" RCA is now one SQL diff between two run_ids on agent search queries',
        'Admin-only + three-headers-present gate ensures prod user traffic never pollutes the eval warehouse',
        'Two surprises caught along the way: JSONB write path was broken (hotfix in same commit) + tracing was OFF in prod despite assumption (now toggled ON)',
        'Verification run landed 34 spans across 8 calibration items + multi-turn mt03 across 3 turns, all columns populated',
      ],
    },
  },
  {
    date: '2026-05-30', slug: 'langfuse-sdk-overhead-rca', milestone: 'v1.8', tag: 'experiment',
    title: {
      zh: '量測證實「外部觀察工具拖慢系統」是誤判 — RCA 兩輪後清白',
      en: 'Measurement Cleared Langfuse Cloud SDK: "It Slows Us Down" Was a False Alarm',
    },
    summary: {
      zh: '昨天 ship 評分框架升級時量到「打開 trace 觀察會讓 P95 延遲 +3.4 秒」、當下推給 Langfuse 雲服務本身慢、開了「自架 Langfuse 評估」當下一條 follow-up。今天 RCA 兩輪。第一輪 review 想「會不會其實是我們自己寫的 PG 雙寫沒做非阻塞」、寫了完整提案 + 設計 + 規格 + 任務、apply 開始時 grep 才發現雙寫 code path 從來沒被觸發過（runner 沒呼叫對應 binding 函式）— 假設破滅、暫存 change。第二輪做了 spike：在 trace 內部四個可疑 Langfuse 呼叫各包 timing wrapper、推到 prod 量。結果：每個 op 都 0.1-0.5 ms 級別、每 span total ~1 ms、30 span/query 也只 ~28 ms total overhead。**完全跟官方說的 0.1ms async-batched 一致**。對比同期跑出來的整體請求 P95 反而比昨天 4.4 OFF baseline **還快 2.3 秒** — 不可能是 SDK 加了 +3.4s。**結論：昨天那輪 +3.4s 是跨 session 量測雜訊**（兩個獨立 session 之間 prod 流量背景 / cache / 網路條件不同）、SDK 是清白的、自架 follow-up 取消。教訓：跨 session P95 比較不能當 RCA attribution 證據、要同 session 內 timing instrumentation 才算數。Spike 工具留在 codebase 預設關、未來想再量直接 toggle 一個環境變數。',
      en: 'Yesterday\'s eval framework ship measured "+3.4s P95 latency when tracing turned on" and we blamed Langfuse Cloud SDK, opening "evaluate self-hosting Langfuse" as the next follow-up. Today: two rounds of RCA. Round 1 hypothesised it was our own PG dual-sink not doing fire-and-forget; wrote full proposal + design + spec + tasks, then grep during apply found the PG sink code path was never triggered (runner never called the binding function). Hypothesis falsified, change parked. Round 2 spike: wrapped four suspect Langfuse SDK calls inside trace_span with `time.perf_counter` timing, deployed to prod, measured. Result: each op 0.1-0.5 ms, per-span total ~1 ms, 30 spans/query = ~28 ms total overhead. **Exactly matches the 0.1ms async-batched figure in official Langfuse docs**. Overall request P95 with tracing ON was actually **2.3s faster** than yesterday\'s 4.4 OFF baseline — definitively not a +3.4s SDK overhead. **Conclusion: yesterday\'s +3.4s was cross-session measurement noise** (prod traffic / cache / network differed between two independent measurement sessions). SDK is innocent, self-host follow-up cancelled. Lesson: cross-session P95 comparison is invalid as RCA attribution evidence; same-session timing instrumentation is required. Spike tooling stays in codebase default-off; re-measurement is one env var toggle away.',
    },
    summaryBullets: {
      zh: [
        '昨天 4.4 量到 +3.4s P95 推 SDK 慢 → 今天 RCA 兩輪後證實 SDK 清白、是跨 session 量測雜訊',
        '加 timing wrapper 量到實際 SDK overhead 0.947 ms/span（與官方 docs 0.1ms 量級一致）',
        '自架 Langfuse follow-up 取消（自架主要動機「拉延遲」不存在）',
        '教訓：跨 session P95 比較不能當 RCA attribution、要同 session 內 timing 證據才算數',
      ],
      en: [
        'Yesterday\'s 4.4 measurement attributed +3.4s P95 to SDK overhead → today\'s 2-round RCA cleared the SDK, was cross-session noise',
        'Timing wrappers showed real SDK overhead is 0.947 ms/span (matches official 0.1ms async-batched figure)',
        'Self-host Langfuse follow-up cancelled (primary motivation "pull down latency" does not exist)',
        'Lesson: cross-session P95 comparison invalid as RCA attribution evidence; same-session timing required',
      ],
    },
  },
  {
    date: '2026-05-30', slug: 'eval-framework-upgrade', milestone: 'v1.8', tag: 'enhancement',
    title: {
      zh: '評分基準升級：6 個新指標 + 兩支「PR 前先驗證」CLI 工具',
      en: 'Evaluation Framework Upgrade: 6 New Metrics + 2 Pre-PR Verification CLIs',
    },
    summary: {
      zh: '升級內部評分基準，避免下次再撞到 2026-05-28 IDF 實驗的觀察盲點。這次的改動使用者體感**沒直接變化**，但對「未來任何 retrieval / prompt 改動的事前驗證流程」是個底層升級。三件事：(1) 接入業界標準的評分套件 DeepEval，新增 6 個語意層級指標 — 像是「答案的關聯度」「檢索片段是否真的覆蓋到答案」「答案是否忠實於檢索片段」等，補既有「比對段落 ID 是否一字不差」這種容易誤判的脆弱指標。實際跑全 34 題基準時，這次新指標就抓到一個關鍵 insight：表面看起來退步 0.1 的 chunk_recall 其實**不是真的退步** — agent 撈到的相鄰段落（差 13 秒）內容跟正確段落實質重疊、答案品質完全沒變，只是 ID 比對嚴格。新指標的「語意 precision 0.92」直接證實 retrieval 仍健康，避免我們花一整週去追一個假退步。(2) 加進 PR template 的兩支 CLI：`retrieve_probe.py` 可以在改 retrieval 前對特定問題跑 episode-scoped 排序檢查、確認 ground-truth 段落還在前 K 名；`prompt_fingerprint_diff.py` 可以在改 prompt 前對比兩個 backend 看 agent 對同一問題會不會生出不同的 search query — 這兩支工具會自動 surface 之前要花幾小時 RCA 才發現的副作用。(3) 接入 Langfuse Cloud trace 觀察，每次 eval 跑都能在網頁上看 chat_agent_turn → llm_call → tool_call 三層 span tree，未來 RCA 不用再翻 log 拼湊。**一個未達設計目標的點**：原本希望 Langfuse SDK 對 prod 流量延遲增量 < 100ms，實際量到 P95 +3.4 秒、retrieval 重的題目 +5-6 秒，遠超預期。對策是維持 prod 預設關閉 tracing（只在 eval 跑時開），並開了「自架 Langfuse 評估」做為下一條 follow-up（自架 LAN 內延遲應該能拉回 <200ms）。',
      en: 'Internal evaluation baseline upgrade — addresses the observability blind spots that caused the 2026-05-28 IDF experiment failure. **No direct user-visible change**, but a foundational upgrade for future retrieval/prompt change verification. Three things: (1) Integrated DeepEval, adding 6 new semantic-level metrics — answer relevancy, contextual recall (whether retrieved chunks cover the GT answer), contextual precision, faithfulness, semantic answer similarity, entity recall. These complement the existing brittle "chunk-ID byte-exact match" indicator. On the full 34-item baseline, the new metrics immediately surfaced an important insight: the apparent chunk_recall -0.1 regression was **not actually a regression** — the agent had landed on adjacent chunks (13s away) with substantively overlapping content, answer quality unchanged. New `contextual_precision=0.92` directly confirmed retrieval was still healthy, saving us a week of chasing a phantom regression. (2) Two new CLIs added to PR template: `retrieve_probe.py` runs episode-scoped ranking checks against specific items to confirm GT chunks are still in top-K before merging retrieval changes; `prompt_fingerprint_diff.py` compares two backends to surface whether the agent rephrases its search queries differently after a prompt change — both tools auto-surface side effects that previously required hours of RCA to find. (3) Langfuse Cloud tracing integration — every eval run emits a chat_agent_turn → llm_call → tool_call 3-level span tree viewable in the web UI, so future RCA no longer requires log-scraping. **One design miss**: the original target was <100ms Langfuse SDK latency overhead on prod traffic; actual measurement was P95 +3.4s, retrieval-heavy queries +5-6s, far exceeding expectations. Mitigation: keep prod tracing default-OFF (eval-only), opened follow-up "evaluate self-hosting Langfuse" — LAN-local RPC should bring it back under 200ms.',
    },
    summaryBullets: {
      zh: [
        '新增 6 個語意層級指標（DeepEval 4 個內建 + GEval 自寫 2 個），補既有「段落 ID 一字不差」這種脆弱指標',
        '新指標立刻抓到：本次全 34 題 baseline 對比上輪「退步 0.1」是假警報、實質檢索健康，省下一週追假退步',
        '兩支 PR 必跑 CLI：retrieve_probe.py 事前驗 GT 段落還在 top-K、prompt_fingerprint_diff.py 事前驗 agent 不會自己改 search query',
        '接 Langfuse Cloud trace 觀察 — eval 跑時可看每個 agent step 的 span tree，未來 RCA 更快',
        '未達設計目標：Cloud SDK 對 prod 延遲增量遠超預期（P95 +3.4s），prod 預設關閉、自架評估 follow-up 升優先',
      ],
      en: [
        'Added 6 semantic-level metrics (4 DeepEval built-ins + 2 GEval custom rubrics), complementing the brittle "chunk-ID byte-exact match" indicator',
        'New metrics immediately caught: this run\'s apparent "chunk_recall -0.1 regression" vs prior baseline was a false alarm — retrieval still healthy, saved a week of phantom-regression chasing',
        'Two PR-mandatory CLIs: retrieve_probe.py pre-validates GT chunks still in top-K, prompt_fingerprint_diff.py pre-detects agent re-phrasing search queries',
        'Langfuse Cloud tracing — eval runs emit a full span tree viewable in web UI, making future RCA significantly faster',
        'Design miss: Cloud SDK latency overhead far exceeded target (P95 +3.4s vs <100ms goal); prod tracing default-OFF, self-host evaluation promoted as follow-up',
      ],
    },
  },
  {
    date: '2026-05-28', slug: 'retrieve-quality-step1-idf-and-prefilter-failed', milestone: 'v1.8', tag: 'experiment',
    title: {
      zh: 'IDF 加權實驗（兩 Layer 都試失敗、已 revert）',
      en: 'IDF Weighting Experiment (Two Layers Tried, Both Reverted)',
    },
    summary: {
      zh: '為了改善「跨集問題」的內部 chunk_recall（從 0.482 想拉到 0.55+），這週試了兩條方向，**兩條都沒過、全部回滾**，使用者體感沒變化、整理一下教訓寫進路線圖避免下次再撞。第一條（Layer A）是給段落關鍵字打分時加上「IDF 加權」— 罕見詞（譬如「振奮」）權重給 1.0、常見詞（「什麼」）給 0.05。直覺上應該讓罕見詞主導排序。實際跑完 34 題內部 baseline：chunk_recall 0.482 → 0.382（退 0.1），7 題退步。Root cause：在 podcast transcript 領域，IDF 假設「罕見詞 = 答案信號」**完全不成立** — 罕見詞往往是「整集主題」（譬如「伴手禮」在那一集滿地都是），加權後反而把「跟主題相關但不是答案」的段落推上去、把真答案擠出 top-K。第二條（Layer B）是改 chat agent 的 prompt，看到「EP134」「第 134 集」這類明確集數 reference 時強制走「先找集數、再在那集內搜尋」。本來假設純 prompt 改、不會動 retrieval。實際 chunk_recall 0.482 → 0.340 退更慘。Root cause：prompt 改了 agent 對同一問題重新措辭 search query 的方式，下游 ts_rank 收到不同 token、命中不同段落 — **prompt change 從來不是 orthogonal 於 retrieval**。兩條教訓 + 一條「show-wide DB probe 是 false positive validator」教訓寫進工程紀錄。**下一步轉向評估框架升級**（per-question tool trace 落地、episode-scoped retrieval probe、span-level metric），先有更好的觀察工具才能避免下次類似盲點再撞。Prod 沒實質變動，僅留下一個未使用的 token-frequency 資料表（無 schema 衝擊，未來實驗可能 reuse）。',
      en: 'Tried two directions this week to push internal cross-episode chunk_recall from 0.482 toward 0.55+; **both failed and were reverted**, no user-visible change, lessons captured to avoid repeats. Layer A added "IDF weighting" to lexical scoring — rare tokens (e.g. "振奮") get 1.0 weight, common tokens ("什麼") get 0.05. Intuitively rare tokens should dominate ranking. Actual 34-item baseline: chunk_recall 0.482 → 0.382 (-0.1), 7 cases regressed. Root cause: in the podcast-transcript domain, the IDF assumption "rare token = answer signal" **completely fails** — rare tokens are usually the episode\'s overall topic (e.g. "伴手禮" appears everywhere within that one episode), so weighting them up promotes "topic-related-but-not-answer" chunks and pushes the actual answer out of top-K. Layer B changed the chat agent\'s prompt to mandate "find episode first, then search within it" for explicit EP-references like "EP134" / "第 134 集". Assumed to be pure prompt nudge with zero retrieval risk. Actual chunk_recall 0.482 → 0.340 (worse than A). Root cause: the new prompt changed how the agent re-phrased its search query for the same user question, downstream ts_rank received different tokens and hit different chunks — **prompt changes are never orthogonal to retrieval**. Two lessons plus a third ("show-wide DB probe is a false positive validator for episode-scoped retrieval") are now in engineering notes. **Next direction pivots to evaluation framework upgrade** (per-question tool trace, episode-scoped retrieval probe, span-level metrics) — better observability tooling first, before touching retrieval or prompts again. No prod functional change; only a leftover unused token-frequency table (no schema impact, possible future-experiment reuse).',
    },
    summaryBullets: {
      zh: [
        '本週試 IDF 加權 + EP-ref dispatch 兩條 retrieval 改善方向 — 兩條都退步、全部 revert，使用者體感沒變化',
        'Layer A (IDF 加權) root cause：podcast domain 罕見詞 = 整集主題、不是答案信號 — 加權把錯段落推上去',
        'Layer B (EP-ref prompt) root cause：prompt 改了 agent 對 search 工具的 query 措辭、下游 retrieval 跟著飄',
        '下動轉向：先升級評估框架（trace 落地 + episode-scoped probe）再動 retrieval，避免再撞觀察盲點',
      ],
      en: [
        'Tried two retrieval-improvement directions (IDF weighting + EP-ref dispatch) — both regressed and were reverted, no user-visible change',
        'Layer A (IDF weighting) root cause: in podcast domain, rare tokens are episode topics not answer signals — weighting them up promoted wrong chunks',
        'Layer B (EP-ref prompt) root cause: prompt nudge changed how the agent worded its search query, downstream retrieval drifted with it',
        'Next pivot: upgrade evaluation framework first (tool trace + episode-scoped probe) before touching retrieval again, to avoid blind spots',
      ],
    },
  },
  {
    date: '2026-05-27', slug: 'judge-pronoun-attribution-check', milestone: 'v1.8', tag: 'enhancement',
    title: {
      zh: '判分 AI 學會看出「把別人的故事套到你問的那個人身上」',
      en: 'The Grading AI Now Catches "Wrong-Person Story Attribution"',
    },
    summary: {
      zh: '修內部「打分 AI」的兩個盲點。第一個盲點是物理層：打分 AI 過去看到的資料只有「摘要」（每段截斷到 500 字），跟回答用的 AI 看到的完整段落（最多 8000 字）不一樣 — 等於用刪節版去判斷一個寫了完整劇本的演員，根本沒上下文。第二個盲點是邏輯層：過去判分 AI 只比對「答案 vs 期望摘要的表面用詞」，看到 b23 那種「段落講的是迪拉跟呂安初遇，但回答 AI 把『他』『我』全套用到 Leo 王身上」的代詞錯誤套用，判分 AI 完全抓不到、還給 0.95 高分。本次修法：(1) 餵完整段落給判分 AI、不再用 500 字截斷版 (2) 新增第 4 個指標「代詞主體驗證」三態：完美對齊 / 合理推測 / 張冠李戴 (3) 用 b23 案例當示範教 AI 怎麼判。完整 34 題重跑後，三大主要指標全部往上：跨集問題抓取準確度 0.382→0.482、答案事實正確性 0.831→0.892、拒答適切性 0.971→1.000；代詞驗證分佈 4 完美對齊 / 1 合理推測 / 0 張冠李戴 / 29 不適用 — 0 個張冠李戴反映前兩週的 dataset + retrieval 修正真實生效，回答 AI 不再撈到無關段落了。對使用者體感無直接影響，但內部評分基準變得更可信，後續任何對話品質改造都有更準的反饋。',
      en: 'Fixed two blind spots in the internal grading AI. Physical blind spot: the grading AI was only seeing a "summary" of each tool result (truncated to 500 chars), while the answering agent saw the full 8000-char chunk — like grading an actor based on a CliffsNotes summary of the script. Logical blind spot: the rubric only compared surface wording between answer and expected, so cases like b23 (where chunks tell a 迪拉-呂安 first-meeting story but the agent maps all the "he/I/we" pronouns onto Leo 王) sailed through with factual=0.95. This change: (1) feeds the full chunk text to the grading AI (no more 500-char truncation), (2) adds a 4th indicator "pronoun attribution check" with three states (grounded / inferred / hallucinated), (3) uses b23 as the canonical example to teach the rubric. After re-running all 34 items, the three main metrics all moved up: cross-episode retrieval precision 0.382→0.482, answer factual correctness 0.831→0.892, refusal appropriateness 0.971→1.000. Pronoun-attribution distribution: 4 grounded / 1 inferred / 0 hallucinated / 29 null — zero hallucinations reflects that the prior two weeks\' dataset + retrieval fixes genuinely solved the b23-class problem (agents no longer reach unrelated chunks). No direct user-facing change, but our internal grading baseline is now trustworthy, giving future chat-mode improvements honest feedback.',
    },
    summaryBullets: {
      zh: [
        '修判分 AI 物理層盲點：從看「500 字摘要」改成看「完整 8000 字段落」，跟回答 AI 看的對齊',
        '新增第 4 個指標「代詞主體驗證」三態：完美對齊 / 合理推測 / 張冠李戴',
        '全 34 題重跑：跨集準確度 0.382→0.482、事實正確性 0.831→0.892、拒答適切性 0.971→1.000，三大指標全提升',
        '0 個張冠李戴 = dataset + retrieval 前置修正真實生效；後續對話模式改造有可信反饋',
      ],
      en: [
        'Fixed grading AI physical blind spot — now sees the full 8000-char chunk instead of a 500-char summary, matching what the answering agent sees',
        'Added 4th indicator "pronoun attribution check" with three states: grounded / inferred / hallucinated',
        'Full 34-item re-eval: cross-episode precision 0.382→0.482, factual 0.831→0.892, refusal 0.971→1.000 — all three main metrics up',
        '0 hallucinations confirms prior dataset + retrieval fixes genuinely solved the b23-class problem; future chat-mode work now has trustworthy feedback',
      ],
    },
  },
  {
    date: '2026-05-27', slug: 'b23-dataset-and-retrieval-rca-fix', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: '從一題對話 mode 答錯案例挖出 4 層連鎖問題',
      en: 'A Single Wrong-Answer Bug Exposed Four Layers of Hidden Issues',
    },
    summary: {
      zh: '從一題對話模式答錯的案例（user 問「迪拉跟 Leo 王怎麼從不認識變成合作夥伴？」），user 親自聽逐字稿驗證後挖出 4 層連鎖問題。第一層是檢索：原本回答把 EP129（迪拉跟「呂安」的故事，跟 Leo 王完全無關）誤當成正確來源。第二層是 LLM 代詞解析：AI 拿到無關段落後自動把段落內的「他」「我」誤套到 query 主體（Leo 王），表面看引用真實逐字稿、實際語意全錯。第三層是內部評分機制：判分用的 LLM 沒有檢查代詞指向是否一致，所以這種「表面 grounded 實際 hallucinate」的回答竟然拿到高分通過。第四層是內部測資本身：dataset 標的「正確段落」之一（EP116 @187.48）也標錯了 — 那段其實是小老虎跟 Leo 王相識的故事，迪拉只是搭橋安排演出，跟「迪拉跟 Leo 王第一次見面」是兩件事。修法：(1) dataset 修兩題的標註 — b23 移除 EP116 標錯段、b22 補上 7 個分散的人物證據段落 (2) 後端 episode finder 新增 guest-index 派遣路徑，當 query 含 ≥2 個可辨識的來賓名稱時，加跑來賓索引找出真有那些人參與的集數 (3) 內部 diagnose 工具擴到 top-500 + 可看前後段落 (4) 把 b20 揭露的另一個 retrieve 召回根本問題（某些段落連 top-500 都沒撈到）紀錄為下一個 follow-up。Prod 重跑：b23 真實提升 chunk_recall 0→0.5，其他題 deep_dive 對照組全部維持。內部評分指標的代詞驗證 + LLM 代詞紀律則記為兩條獨立 follow-up，不在本次 scope。',
      en: 'A single wrong-answer case in chat mode (user asked "how did 迪拉 and Leo 王 go from strangers to collaborators?") cascaded into four hidden issues, exposed only after the user personally listened to the cited transcript. Layer 1 was retrieval: the answer was sourced from EP129 (a story about 迪拉 and 呂安, entirely unrelated to Leo 王). Layer 2 was LLM pronoun resolution: the AI took the unrelated chunk and auto-mapped pronouns like "he/I" to the query subjects, producing an answer that looked grounded but was semantically wrong. Layer 3 was the internal evaluation grader: the LLM judge didn\'t verify pronoun-referent consistency, so "looks grounded but actually hallucinated" answers got high scores. Layer 4 was the dataset itself: one of the "correct ground-truth chunks" (EP116 @187.48) was also mislabelled — that segment is actually about 小老虎 meeting Leo 王 (迪拉 was just the venue arranger), not 迪拉 meeting Leo 王. Fixes: (1) dataset corrections for two items — b23 removed the mislabelled EP116 chunk; b22 added 7 person-evidence chunks; (2) backend episode finder gained a guest-index dispatch path that triggers when a query mentions ≥2 known guest names; (3) admin diagnose endpoint extended to top-500 with neighbour-chunk context; (4) the orthogonal retrieve_hybrid recall gap exposed by b20 (some ground-truth chunks not even in top-500) is filed as a separate follow-up. Prod re-eval: b23 chunk_recall improved from 0 → 0.5; deep_dive control group all unchanged. LLM pronoun grounding + judge pronoun-attribution checks remain separate follow-ups, deliberately out of scope.',
    },
    summaryBullets: {
      zh: [
        '一個對話模式答錯案例挖出 4 層問題：retrieval miss + LLM 代詞 hallucinate + judge 抓不到 + dataset 也標錯',
        'b23 真實提升：chunk_recall 0→0.5；dataset 內部測資的代詞驗證紀律寫進 spec',
        '後端新增 guest-index 派遣路徑，未來涉及多人關係的 query 可走來賓索引而非主題索引',
        '內部 diagnose 工具擴到 top-500 + 看前後段落，揭露 b20 的另一個 retrieve 召回根本問題（留 follow-up）',
        'LLM 代詞解析 grounding + judge 代詞驗證留為兩條獨立 follow-up',
      ],
      en: [
        'A single wrong-answer case exposed 4 layers: retrieval miss + LLM pronoun hallucination + judge blind spot + dataset mislabel',
        'b23 real improvement: chunk_recall 0→0.5; dataset pronoun-referent verification discipline now in spec',
        'Backend added guest-index dispatch — multi-person-relationship queries can route via guest index instead of topic index',
        'Admin diagnose extended to top-500 with neighbour context, exposing a separate retrieve_hybrid recall gap (filed as follow-up)',
        'LLM pronoun grounding + judge pronoun-attribution checks filed as two independent follow-ups',
      ],
    },
  },
  {
    date: '2026-05-27', slug: 'eval-baseline-citation-bug-revalidation', milestone: 'v1.8', tag: 'enhancement',
    title: {
      zh: '對話模式內部評分數據洗乾淨了，找到下一步該動哪裡',
      en: 'Chat-Mode Eval Baseline Cleaned; Next Bottleneck Identified',
    },
    summary: {
      zh: '回頭洗一筆內部數據污染。上週新增「主題預過濾」檢索工具後，agent 在這條路徑撈到的段落沒被內部評分機制納入計算（程式有個白名單漏更新），導致連續好幾天的「跨集問題」評分數據都被低估到 0 — 我們以為改善沒效果，其實是評分本身在說謊。修白名單之後（commit 287e73b）重跑全 34 題乾淨基準，發現「跨集問題」真實的內部 chunk_recall 是 0.283，而非過去誤以為的 0.244；過去三個 archive change 的對照基準需要重新解讀。重洗過程順手把 4 道跨集題（b20/b21/b22/b23）的內部 retrieve 結果與 ground truth 命中位置全部列出來放大鏡 audit，發現 b22 / b23 退步的真實原因不是 rerank 排序問題（rerank 改不到 root cause），而是 b22 屬於「LLM 答案策略題」、b23 是「主題預過濾的候選集找錯」— 這個發現直接讓原本計畫的 voyage-rerank-tune-b22-b23 change 可以改寫為兩條更精準的子 change（topic-finder 強化 + meta-question 答案策略），省下一輪錯誤方向的調整。對使用者直接體感沒變化，但內部評分數據從此可信，且下一步的優化方向更明確。',
      en: 'Cleaned up internal eval data contamination from the past week. After adding the "topic-prefilter" retrieval tool last week, chunks returned via that path were not being counted by the internal scoring mechanism (an unsynced whitelist), making the "cross-episode" question scores look flat at zero for several days — we thought our improvements were not working, when actually the scoring itself was lying. After fixing the whitelist (commit 287e73b), we re-ran the full 34-item clean baseline and found the real internal chunk_recall for cross-episode questions is 0.283, not the 0.244 we had been comparing against; three recently archived changes need their "vs baseline" verdicts re-read. While we were at it, we put all four cross-episode questions (b20/b21/b22/b23) under a microscope — listing their retrieved chunks vs ground-truth chunk positions — and discovered the real reason b22/b23 regressed is NOT a rerank ordering problem (rerank cannot reach the root cause). b22 is actually an "LLM answer-strategy" question type and b23 is a "topic-prefilter picks the wrong candidate episodes" problem. This finding lets us rewrite the originally planned voyage-rerank-tune-b22-b23 change into two more targeted sub-changes (topic-finder hardening + meta-question answer strategy), saving a round of misdirected tuning. No direct user-visible behavior change, but internal eval data is now trustworthy, and the next direction of work is much clearer.',
    },
    summaryBullets: {
      zh: [
        '修內部評分白名單漏更新（commit 287e73b），洗掉過去一週「跨集問題」評分被低估到 0 的污染數據',
        '真實內部基準 cross_episode chunk_recall = 0.283（過去以為的 0.244 已 deprecated）',
        '對 b20/b21/b22/b23 做完整放大鏡 audit，揭露「b22/b23 退步」真因不在 rerank',
        '原本計畫的 voyage-rerank-tune-b22-b23 change 可重寫為兩條精準子 change，省一輪錯誤方向的調整',
      ],
      en: [
        'Fixed internal-scoring whitelist gap (commit 287e73b), cleaning up a week of "cross-episode" scores misreported as 0',
        'Real internal cross_episode chunk_recall = 0.283 (the 0.244 we had been comparing to is now deprecated)',
        'Full microscope audit on b20-b23 revealed b22/b23 regressions are NOT rerank issues',
        'Originally planned voyage-rerank-tune change can be rewritten as two targeted sub-changes, saving a round of misdirected work',
      ],
    },
  },
  {
    date: '2026-05-26', slug: 'retrieval-cross-episode-episode-prefilter', milestone: 'v1.8', tag: 'enhancement',
    title: {
      zh: '跨集問題不再被別集話題沖淡',
      en: 'Cross-Episode Questions No Longer Diluted by Off-Topic Episodes',
    },
    summary: {
      zh: '改善「跨集主題型」問題的檢索路徑。過去你問「節目裡迪拉怎麼描述中老年人的開工想法跟年輕時的差異？」這種需要跨集合成觀點的問題，agent 會把全節目所有集數的相關段落混在一起排序，結果常被別集主題接近但實際不相關的段落擠進前 5 名（譬如「家常味」主題的話題會混進「開工」主題的回答池），合成的答案就會被稀釋。這次新增了一個檢索工具，agent 會先把問題裡的主題（譬如「開工」）拿去找出真的有講這個主題的候選集（譬如 EP134 開工歌單那集），只在那幾集內做檢索 — 找不到候選才退回全節目搜尋。Prod 驗證：cross_episode 4 題中 2 題 agent 自發採用新工具（採用率 50%），且 b20 那題的回答從「在多集合成」變成「鎖定 EP134 馬力全開的開工歌單」單集為基礎正確作答，不再被別集污染。但內部 chunk_recall 指標還沒改善（0.244 持平）— 因為「縮對候選池」之後，主集內排序前 5 仍然漏掉黃金段落，瓶頸從「跨集污染」轉到「單集內排序」，已立後續 follow-up 處理。',
      en: 'Improves retrieval for cross-episode topical questions. Previously, asking something like "how does 迪拉 describe middle-aged vs. young people\'s feelings about starting work after the new year?" — which needs synthesizing a view across episodes — would dump all show-wide chunks into one ranked pool, often letting topic-adjacent but actually unrelated chunks (e.g. "家常味" chunks bleeding into "開工" questions) crowd out the top 5, diluting the synthesized answer. We added a new retrieval tool that first finds the candidate episodes that actually discuss the topic the question is about (e.g. EP134\'s "馬力全開的開工歌單" for "開工"-topic questions), then searches only within those candidates — falling back to a full-show search if no candidates match. Prod verified: 2 of 4 cross-episode questions had the agent self-adopt the new tool (50% adoption rate), and the b20 question\'s answer shifted from "synthesizing across episodes" to "grounded in EP134 alone" with no off-episode pollution. The internal chunk_recall metric did not move (0.244 flat) — once the candidate pool is correctly narrowed, the top-5 ranking inside the main episode still misses the gold-standard chunks. The bottleneck shifted from "cross-episode pollution" to "in-episode ranking", which is filed as a separate follow-up.',
    },
    summaryBullets: {
      zh: [
        '新增「主題預過濾」檢索工具：先找對的集再檢索，不再讓別集話題擠進回答池',
        'Agent 自發採用率 cross_episode 50%（4 題中 2 題），不靠改 SYSTEM_PROMPT 而靠工具描述讓 LLM 自己選對工具',
        'b20 案例驗證：回答從「跨集合成」變成「鎖定 EP134 單集為基礎」，無別集污染',
        '內部指標 chunk_recall 沒改善 — 縮對池後，主集內前 5 排序仍漏黃金段落，已立 follow-up',
      ],
      en: [
        'New "topic-prefilter" retrieval tool: narrows to the right episodes first, no more off-episode chunks crowding the answer pool',
        'Cross-episode adoption rate 50% (2/4) — achieved via tool description, not SYSTEM_PROMPT changes (avoids prompt saturation)',
        'b20 validated: answer shifted from "synthesized across episodes" to "grounded in EP134 alone", no pollution',
        'Internal chunk_recall metric flat — bottleneck moved to in-episode ranking; filed as separate follow-up',
      ],
    },
  },
  {
    date: '2026-05-26', slug: 'multi-turn-epref-resolution-fix', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: '對話模式追問特定集數時不再亂掉',
      en: 'Chat Mode No Longer Loses Track of Episodes Across Follow-Up Questions',
    },
    summary: {
      zh: '修對話模式多輪追問的兩個討厭問題。第一個：你先問「EP140 第二彈是哪兩位來賓？」，agent 答對楊大正跟張凱婷；緊接著追問「他們推薦哪間餐廳？」，agent 卻會回「集數編號 140 的格式是否正確？請提供 UUID」直接放棄 — 因為它在第一輪識別了 EP140 但沒記住，第二輪不知道你在問哪集。第二個：類似情境下 agent 有時不放棄，反而漂到別集 — 你問 EP19 的動漫歌單，追問「大家推薦了哪些歌？」結果跳到 EP112 來答，再追問「這些歌出自哪部作品？」更扯，agent 編造「EP112 和 EP46 是否是完整的節目編號？」整個迷路。修法是讓 agent 在識別到某一集後自動把焦點鎖定到那一集，後續追問如果沒明確說別的集就會自動繼續在那一集裡查 — 純機械邏輯，不靠改 SYSTEM_PROMPT 讓 LLM「學」這個習慣。Prod 驗證：mt02/mt03/mt04 三題的「放棄」「漂到別集」「編造集號」全部消失；同時 mt01 的「第三集是什麼」這類序數指代問題仍 fail（屬另一個 mechanical fix follow-up，刻意不在這次 scope 內以保持隔離）。',
      en: 'Fixes two annoying chat-mode multi-turn behaviors. First: ask "who were the two guests on the EP140 second course episode?", agent correctly says 楊大正 and 張凱婷; immediately follow up with "which restaurants did they recommend?", and agent returns "is episode number 140 in the correct format? please provide UUID" — it identified EP140 in turn 1 but didn\'t remember, so turn 2 has no idea which episode you mean. Second: in similar scenarios agent sometimes doesn\'t give up — it drifts to a completely different episode. Ask about EP19\'s anime playlist, follow up with "what songs did they recommend?" and it switches to EP112 instead; follow up once more with "what works are those songs from?" and agent makes up "EP112 and EP46 — are those complete episode numbers?", fully lost. Fix: when agent resolves an episode reference, the tool layer auto-pins focus to that episode; subsequent turns that don\'t mention a different episode will transparently scope queries to the pinned one. Pure mechanical wiring — no SYSTEM_PROMPT changes asking the LLM to "learn" this habit. Prod verified: mt02/mt03/mt04 all stopped giving up / drifting / fabricating episode numbers. mt01\'s "what\'s the third episode?" ordinal-reference bug remains failing (deliberately out of scope for this change to keep cause-and-effect isolated — separate follow-up).',
    },
    summaryBullets: {
      zh: [
        '多輪對話中追問「他們推薦哪間餐廳」這種延續題不再被 agent 反問「請提供 UUID」放棄',
        '不會再從 EP19 追問突然漂到 EP112、EP46 這種完全不相關的集數',
        '靠 tool 層機械 auto-pin，不動 SYSTEM_PROMPT（避免 prompt 飽和風險）',
        '序數指代問題（「第三集是什麼」）仍 fail — 屬另一個 follow-up，本次刻意隔離',
      ],
      en: [
        'Follow-up questions like "what restaurants did they recommend" no longer get refused with "please provide UUID"',
        'Asking about EP19 then following up no longer drifts to unrelated episodes like EP112 or EP46',
        'Achieved via mechanical auto-pin at the tool layer — no SYSTEM_PROMPT changes (avoids prompt saturation risk)',
        'Ordinal reference bug ("what\'s the third episode") still fails — separate follow-up, deliberately out of scope',
      ],
    },
  },
  {
    date: '2026-05-26', slug: 'eval-judge-incorporate-tool-grounding', milestone: 'v1.8', tag: 'enhancement',
    title: {
      zh: '對話模式的品質量得更準了',
      en: 'Chat Mode Quality, Now Measured More Sharply',
    },
    summary: {
      zh: '把「對話模式答得好不好」的內部量尺整個重做。過去用「答案裡有沒有出現某幾個關鍵詞」算分，遇到語意對但用詞不同（譬如預期「公務人員」、agent 答「電信局」，其實是同個意思）會誤判扣分；也擋不住「兜兩邊話術」這種典型錯誤（譬如問「為什麼不挑振奮歌」、agent 答「他也推薦振奮人心的歌」直接違反題目前提）；更看不出 agent 在多輪對話「第三集」這類序數指代時，到底有沒有正確抓到應該指的那一集。新版量尺改用 LLM 看完整 agent 工具呼叫紀錄（不只看最後一句回答）來打分，且加了三個新指標：判斷答案內提到的集數數字跟系統實際撈到的集數對不對得上（抓 LLM 數字嘴砲）、抓答案是否違反問題前提（contradict_check）、抓多輪序數指代有沒有解析到正確集數（ordinal_resolution_check）。同步重做 dataset schema 支援「必中集合 / bonus 集合」兩層 + 「重疊段落擇一即算」三層 chunk ground truth，解過去 chunk 切分跨邊界時會被冤枉扣分的問題。對使用者直接體感沒有變化，但這層基礎建設讓往後修對話模式的功能有更精準的反饋，避免再被指標本身的盲點帶歪方向。',
      en: 'Rebuilt the internal yardstick for "how good is the chat mode\'s answer". The old grader scored by checking whether specific keywords appeared in the answer, which mis-judged semantically correct answers using different wording (e.g. expected "civil servant", agent said "telecom bureau employee" — same meaning); it also couldn\'t catch "argue both sides" failures (e.g. ask "why didn\'t he pick an upbeat song", agent answers "he also recommended upbeat songs" — directly contradicts the question premise); nor could it tell whether the agent correctly resolved "the third episode" in multi-turn ordinal references. The new grader uses an LLM that sees the full agent tool-call trace (not just the final answer text) and adds three new indicators: whether the count the agent mentions matches what the tool actually returned (catches LLM number hallucination), whether the answer violates the question premise (contradict_check), and whether multi-turn ordinal references resolve to the correct episode (ordinal_resolution_check). Also reworked the dataset schema to support two-tier "must-hit / bonus" episode sets and three-tier "either one counts" chunk ground truth, fixing cases where overlapping chunk boundaries unfairly penalized correct retrieval. No direct user-visible behavior change — this infrastructure makes future chat-mode work measurable instead of vibes-based, so we don\'t get misled by metric blind spots.',
    },
    summaryBullets: {
      zh: [
        '評分改用 LLM 看完整 agent 工具紀錄打分，解語意同義被誤判的問題',
        '抓「兜兩邊話術」「LLM 數字嘴砲」「多輪序數指代抓錯集數」三類過去看不出來的錯誤',
        'Dataset 改三層 ground truth 結構，重疊段落不再冤枉扣分',
        '使用者體感沒變，純粹讓往後對話模式的優化決策有可信的反饋',
      ],
      en: [
        'Switched to LLM-judge grading over full agent tool trace, fixing semantic-synonym false negatives',
        'Catches three previously invisible failure modes: argue-both-sides, LLM number hallucination, multi-turn ordinal mis-resolution',
        'Three-tier ground-truth structure stops overlapping chunk boundaries from being unfairly penalized',
        'No user-visible change — pure foundation work so future chat-mode improvements have trustworthy feedback',
      ],
    },
  },
  {
    date: '2026-05-24', slug: 'agentic-severe-residual-fix-2026-05', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: '對話模式查特定集數不再亂回別集',
      en: 'Chat Mode No Longer Returns the Wrong Episode for "EP1" Queries',
    },
    summary: {
      zh: '修兩個對話模式偷偷會出錯的場景。第一個：問「EP1 講什麼」這種具體集數參考，後端 SQL 之前用模糊比對抓「title 含 EP1 字串」的集數，結果 EP10、EP100、EP146 也會被撈到，再按發布日期排序取最新 → 你問 EP1 系統卻回 EP146。改成正規表達式精確比對「EP 1 後面不接其他數字」之後，問 EP1 找不到就老實說查不到，不再撈到別集。第二個：問「節目主持人陣容怎麼變化」這類問題，過去資料庫並沒有主持人變動紀錄，agent 卻會從集數列表硬推「初期主持人是 X、後期是 Y」這種編造內容。SYSTEM_PROMPT 補了「主持人變動類問題沒明確紀錄就必須拒答」的強制規則。順手在後台 admin debug_trace 模式加了個 enumeration_state 觀測欄位，未來 diagnose 多輪對話「第 N 集」這類問題時可以直接看到 state 內容。本輪也試了 post-generation 把不在 tool result 的 EP 號碼標 [未驗證] 的策略，但實測 LLM judge 看到滿屏 [未驗證] 反而把答案打成更差 → 已 revert，留 helper 供未來 silent 模式用。',
      en: 'Fixes two quiet bugs in chat mode. First: asking about a specific episode like "what does EP1 talk about?" used to return the wrong episode (e.g. EP146) because the backend SQL did fuzzy substring matching on titles — EP10/EP100/EP146 all contain "EP1" as a substring, and the most recent one would win. Now uses a word-boundary regex that matches "EP 1 not followed by another digit" exactly. Asking EP1 when it doesn\'t exist now honestly returns "not found" instead of substituting a different episode. Second: asking "how has the host roster changed over time?" used to make the agent infer a host timeline from the episode list and fabricate names. The SYSTEM_PROMPT now contains an explicit rule that this question must be refused unless there\'s an explicit host-change marker in a tool result. Also added an enumeration_state field to the admin debug_trace view for diagnosing "what was the 3rd episode?"-style multi-turn questions. A post-generation "[未驗證]" annotation experiment was reverted — the LLM judge penalized answers cluttered with that tag instead of rewarding the honesty. Helper kept in code for a future silent-mode rework.',
    },
    summaryBullets: {
      zh: [
        '問「EP1 有講什麼」不會再被回 EP146 之類完全不同的集數',
        '問「主持人陣容變化」不會再從集數列表硬推「初期主持人是某某」這種編造',
        'Admin debug_trace 模式新增 enumeration_state 觀測，多輪 ordinal 對話 diagnose 變直接',
        '剩下 multi-turn「第 N 集」這類 LLM 不遵守序數規則的情況留下一輪用 mechanical resolution 處理',
      ],
      en: [
        'Asking "what about EP1?" no longer returns a completely different episode like EP146',
        'Asking "how has the host roster changed?" no longer fabricates host names from the episode list',
        'Admin debug_trace now exposes enumeration_state for easier multi-turn ordinal diagnosis',
        'Remaining multi-turn "Nth episode" misfires (LLM ignoring ordinal instruction) deferred to a future mechanical-resolution change',
      ],
    },
  },
  {
    date: '2026-05-24', slug: 'agentic-grounding-prompt-tune-v2', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: '節目沒講的內容不會再亂編',
      en: 'Chat Mode Stops Making Things Up',
    },
    summary: {
      zh: '修對話模式幻覺問題。上次補的「不能編造」清單只是寫進 SYSTEM_PROMPT，這次根據實測量化結果（嚴重幻覺率 22.5% 反而比之前 baseline 20% 還差），先把 9 個嚴重案例 + 11 個輕微案例的 root cause 分類過一輪，發現 78% 是「tool 查到相關但不含答案的段落，agent 就從這些 noise 裡推論編造」——例如問「嘻哈饒舌歌唱比賽冠軍是誰？」搜到的其實是大嘻哈時代的評審 panel，agent 就把評審名字當冠軍寫出來。對症加了兩個 few-shot 範例（noise 拒答 + show overview 不存在節目拒答），加上把 grounding 規則段提前到緊跟 tool-eager 之後。結果：嚴重幻覺率從 22.5% 砍到 12.5%（-44%），整體回答品質從 0.5375 提升到 0.6625（+12.5pp）。試過再加第三個「negative trap」範例反而讓 prompt 稀釋導致 regress，所以 round 2 直接 revert，剩下的 12.5% 留到下一輪用 tool layer 的方式處理（譬如加 get_show_overview 專屬 tool）。',
      en: 'Fixes hallucination in chat mode. The previous "do not fabricate" list only made it into SYSTEM_PROMPT without measurement — turned out the eval showed severe hallucination rate 22.5% (worse than the 20% baseline). This round we first classified the 9 severe + 11 mild cases by root cause and found 78% were "tools returned topic-related but answer-empty chunks, and the agent inferred a fabrication from the noise" — e.g. asking "who won the hip-hop championship?" surfaced judge panel chunks from the show 大嘻哈時代, and the agent wrote the judges in as winners. Targeted fix: two few-shot examples (noise refusal + show-overview-on-missing-show refusal) plus moving the grounding rule section to immediately after the tool-eager instruction. Result: severe hallucination rate 22.5% → 12.5% (-44%), overall answer quality 0.5375 → 0.6625 (+12.5pp). A round 2 attempt to add a third "negative trap" few-shot diluted the prompt and regressed severe back to 17.5%, so it was reverted. The remaining 12.5% will be tackled in the next round via a tool-layer approach (e.g. a dedicated get_show_overview tool).',
    },
    summaryBullets: {
      zh: [
        '問「也好吃」這種不存在的節目，不會再憑名稱腦補節目介紹',
        '問「嘻哈饒舌冠軍」這種 podcast 沒提的問題，會老實答「節目未提及」不會把評審當冠軍',
        '整體回答品質從 0.5375 升到 0.6625（+12.5pp）— grounding 變嚴 ≠ 全拒答爛答',
        '剩下的硬骨頭（negative trap 陷阱題）prompt 已到飽和，留待下一輪改 tool',
      ],
      en: [
        'Asking about a non-existent show (e.g. 也好吃) no longer triggers a made-up show description',
        'Asking about facts the podcast never mentioned (e.g. "who won the rap championship?") now honestly returns "not mentioned" instead of promoting a judge to winner',
        'Overall answer quality jumped 0.5375 → 0.6625 (+12.5pp) — stricter grounding did not collapse into uniform refusals',
        'The remaining hard cases (negative-trap questions) have hit prompt saturation; next round will tackle them at the tool layer',
      ],
    },
  },
  {
    date: '2026-05-24', slug: 'agentic-prompt-grounding-and-ordinal-tool', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: '對話模式找「最新 / 最舊集數」變聰明',
      en: 'Chat Mode Recency Lookup Now Works',
    },
    summary: {
      zh: '修對話模式抓不到「最新一集 / 最舊五集 / 2024 年最後一集歌單 / 上週最舊一集」這類 recency 問題的問題。之前問「最新一集的來賓是誰？」對話 agent 會直接放棄回「無法確認」，因為手上沒有任何能 sort + limit 的工具。這次補了一個 list_episodes tool，可以指定要幾集 + 最新 / 最舊 + 可選 topic / 年份 filter，agent 看到 recency 問題就會用它。同時把既有的「找某段日期的集數」工具也補了排序 + 數量上限參數，「上週最舊一集」這類問題現在會自己算 datetime range + limit=1 直接答出真實 EP 編號。順手把對話 agent 的 SYSTEM_PROMPT 補了「絕對不能編造」清單（節目名 / 來賓姓名 / EP 編號 / 集數標題 / 來賓引號內的話 / 統計數字）— 部分場景有效（問不存在的來賓直接說查不到、不亂編節目名），但 LLM judge eval 量化顯示 hallucination severe rate 沒有顯著下降，需要下一輪 prompt 重做才能根治。',
      en: 'Fixes "find latest / oldest episodes" queries in chat mode. Previously, asking "who was the guest on the latest episode?" would have the chat agent give up with "cannot confirm" because no existing tool could sort + limit. This change adds a list_episodes tool — specify how many episodes, newest or oldest, with optional topic / year filters. The existing date-range tool also gained sort + limit kwargs, so "the oldest episode from last week" now correctly computes a 7-day window with limit=1. Also added a "do not fabricate" list to the chat agent SYSTEM_PROMPT (show names, guest names, EP numbers, episode titles, quoted lines, counts) — partial wins in simple refusal cases (asking about a non-existent guest returns an honest "not found" instead of making one up), but LLM-as-judge evaluation shows hallucination severe rate did not materially drop; a second prompt iteration is needed.',
    },
    summaryBullets: {
      zh: [
        '問「最新三集是哪些」「最舊五集是哪些」「2024 年最後一集歌單」現在會直接答出真實 EP',
        '問「上週最舊一集」會自己算 7 天日期範圍 + 取最舊 1 集，不再放棄',
        '問不存在的來賓 / 不存在的引號內句子，會老實說「查不到」不再亂編',
        '對「節目整體風格」這類推論題，目前還沒嚴格加註「請以節目實際內容為準」— 留下一輪 prompt 重做',
      ],
      en: [
        'Asking "latest 3 episodes / oldest 5 episodes / last 2024 playlist episode" now returns real EPs',
        '"Oldest episode from last week" auto-computes a 7-day range + limit=1, no more give-up',
        'Asking about non-existent guests or fabricated quotes now honestly returns "not found"',
        'Inference questions ("what\'s the show\'s overall style?") do not yet append the "please verify against the actual content" disclaimer — left for the next prompt iteration',
      ],
    },
  },
  {
    date: '2026-05-23', slug: 'admin-quota-bypass-fix', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: 'Admin 帳號跑 eval 不再被自己擋',
      en: 'Admin Accounts No Longer Block Themselves on Quota',
    },
    summary: {
      zh: '修一個藏起來但卡住整條 eval pipeline 的問題：admin 帳號跟一般使用者一樣每天扣 30 次 chat quota，跑一輪 token-truncate eval gate（34 record × 平均 3 turn ≈ 102 個 chat 請求）開頭就把自己 quota 燒光，後續全部撞 HTTP 429 quota_exhausted，結果這輪 eval 的 answer_match 跌到 0.025（垃圾值）完全沒驗到 token-truncate 真實 fix 效果。修法簡單：backend `/query` endpoint 進來先看 `user.role`，admin 直接 bypass quota 扣減（total_queries 仍 +1 保留可觀測），response 回 `quota_remaining=-1` sentinel 表示無上限。一般使用者扣 quota / 收 429 行為完全不變。修完重跑同一輪 eval：35 個連續 admin chat request 全 HTTP 200、answer_match 從 0.025 → 0.595（A6 達標 ≥ 0.5），順便驗證了上一個 token-truncate fix 在 b20「中老年人開工想法」這題 0 個 turn 爆 context（之前固定 209751 tokens 噴 5xx）。',
      en: 'Fixes a hidden-but-pipeline-blocking issue: admin accounts shared the same daily 30-chat quota as regular users, so running a single token-truncate eval gate (34 records × ~3 turns ≈ 102 chat requests) burned through the admin quota in the first batch and the rest of the run hit HTTP 429 quota_exhausted, dragging answer_match down to 0.025 (garbage) and completely missing the real token-truncate fix signal. Fix is simple: the backend `/query` endpoint now checks `user.role` first — admins skip quota decrement entirely (total_queries still increments for observability) and the response carries `quota_remaining=-1` as the unlimited sentinel. Non-admin quota behavior and 429 handling are unchanged. After the fix, the eval re-run: 35 sequential admin chat requests all returned HTTP 200, answer_match jumped from 0.025 → 0.595 (meets A6 ≥ 0.5), and the b20 "middle-aged people on starting work" question (which previously blew 209751 tokens into a 5xx) returned 0 truncated turns — also confirming the earlier token-truncate fix is doing its job.',
    },
    summaryBullets: {
      zh: [
        'Admin 帳號跑 chat 不再扣 quota、不會撞自己 429',
        'total_queries 仍計數，admin 使用量還是看得到',
        '一般使用者扣 quota / 收 429 的行為完全不變',
        '解開 eval pipeline 卡住：token-truncate fix answer_match 0.025 → 0.595',
      ],
      en: [
        'Admin chat requests no longer decrement quota and never hit self-induced 429',
        'total_queries still increments so admin usage stays observable',
        'Non-admin quota decrement and 429 behavior are unchanged',
        'Unblocks the eval pipeline: token-truncate fix answer_match 0.025 → 0.595',
      ],
    },
  },
  {
    date: '2026-05-23', slug: 'landing-redesign-hotfix-transcript-and-audio', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: '逐字稿、音訊播放、節目簡介都修好了',
      en: 'Transcript Reading, Audio Playback, and Show Descriptions All Fixed',
    },
    summary: {
      zh: '修了介面改版上線後抓到的 4 個視覺問題：(1) 點進逐字稿頁原本一集 80 分鐘的對話會擠成一大塊牆，看不到段落切點 — 現在自動切成 100 段左右，每段都帶時間戳，要找某一句話直接掃就好。(2) 「從此處播放」按鈕原本根本沒出現，整個站沒有任何方式聽音訊 — 現在按鈕固定在逐字稿頁右上角，點下去開始播 + 底部浮出迷你 player，切回查詢頁繼續播不中斷。(3) 搜尋結果點「跳到這段內容」原本只跳到頁首，現在會 scroll 到對應時間的段落並標亮。(4) 首頁節目卡片原本會看到 `<p>` `<br />` 這些原始 HTML 標籤外漏，現在乾淨的純文字 + 自動換行。順手也修了一個 pre-existing bug：逐字稿用 UUID 對應 segment 但用 parseInt 解析，導致段落內容對不上 — 一起整理掉。',
      en: 'Fixes 4 visual regressions found after the landing redesign shipped: (1) Transcript pages used to render an 80-minute episode as one giant wall of text — now auto-split into ~100 paragraphs, each with a timestamp, so you can scan to find a quote. (2) The "Play here" button never rendered, leaving the site with no way to play audio — now it sits fixed on the transcript top bar, clicking starts playback + a mini player floats at the bottom and keeps playing when you navigate back to the query page. (3) "Jump to this segment" links from search results used to only scroll to the top — now they scroll to the matching timestamp paragraph and highlight it. (4) Show description cards on the home page used to leak raw `<p>` `<br />` HTML tags — now clean plain text with auto line-breaks. Also picked up a pre-existing bug where transcript paragraphs used parseInt to map UUID segment ids, mis-targeting content — patched along the way.',
    },
    summaryBullets: {
      zh: [
        '逐字稿不再整集擠一塊，自動切成多段帶時間戳',
        '逐字稿頁右上角「從此處播放」按鈕回來了，底部浮出 mini player',
        '音訊跨頁繼續播，不會被切回查詢頁中斷',
        '搜尋結果「跳到這段內容」真的會 scroll 到對應段落',
        '首頁節目簡介不再顯示原始 HTML 標籤',
      ],
      en: [
        'Transcripts no longer render as one wall of text — auto-split with timestamps',
        '"Play here" button now appears on the transcript page; mini player floats at the bottom',
        'Audio keeps playing across page navigation, no more interruption',
        '"Jump to this segment" links actually scroll to the correct paragraph',
        'Home-page show descriptions render as clean text, no more raw HTML tags',
      ],
    },
  },
  {
    date: '2026-05-23', slug: 'agent-token-budget-and-tool-truncate', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: '對話模式不會再因為單題太複雜直接出錯',
      en: 'Chat Mode No Longer Crashes on Heavy Cross-Episode Questions',
    },
    summary: {
      zh: '修一個邊界但會炸的問題：問「節目裡迪拉怎麼描述中老年人的開工想法跟年輕時的差異」這類需要跨多集多輪 tool 查詢的問題時，AI 累積太多搜尋結果，整個對話超過 gpt-4o 128K context 上限，prod 直接 HTTP 500 噴錯給使用者。修法三層：(1) AI 每次 tool 查詢結果送回給模型前先截到 8K 字（前端 admin 觀測還是看得到全長）(2) 每輪 AI 呼叫前估算 messages 累積 token 數，超 100K 就從前面砍掉最舊的 tool 結果（保留 system prompt 跟最後一輪對話）(3) 真的不小心爆 context 時 catch BadRequestError 改回使用者友善訊息「這題涉及內容太多，我只能列出部分結果；試試把問題拆小，譬如指定單一集數」標 agent_truncated 收尾，不再 5xx。Prod smoke 5/5 全 HTTP 200，b20「中老年人開工想法」這題之前固定爆 209751 tokens 現在穩定回答。',
      en: 'Fixes an edge-but-explosive issue: questions like "How does Dila describe middle-aged people\'s views on starting work versus when they were young?" require cross-episode multi-turn tool lookups, and the accumulated search results pushed the conversation past gpt-4o\'s 128K context limit, returning HTTP 500 to the user. Three-layer fix: (1) tool results are truncated to 8K chars before being sent back to the model (admin trace still sees the full result); (2) before each LLM round, estimate accumulated message tokens; if over 100K, pop the oldest tool results (keeping system prompt + last conversation turn); (3) if context truly overflows, catch BadRequestError and return a user-friendly message "This question covers too much content; I can only list partial results — try narrowing your question, e.g. specify a single episode" with agent_truncated=True, no more 5xx. Prod smoke 5/5 all HTTP 200; the b20 question that previously hit 209751 tokens consistently now answers stably.',
    },
    summaryBullets: {
      zh: [
        '對「跨多集 / 多輪查詢」類問題不再 5xx',
        'AI 看到的 tool 結果有上限（8K 字），admin trace 仍保留全長',
        '超過 context budget 自動裁掉最舊的 tool 結果，保留 system prompt + 最後對話',
        '真的爆掉改回使用者友善訊息，不再露出內部錯誤',
      ],
      en: [
        'Multi-episode / multi-turn lookup questions no longer return 5xx',
        'Tool results sent to the model are capped (8K chars); admin trace keeps full content',
        'When over budget, oldest tool results are dropped; system prompt + last turn preserved',
        'If context truly overflows, a friendly user-facing message replaces the raw error',
      ],
    },
  },
  {
    date: '2026-05-22', slug: 'landing-and-mode-orchestration-redesign', milestone: 'v1.8', tag: 'ui',
    title: {
      zh: '首頁 + 三模式編排大改版：一頁挑節目、看懂模式、直接出發',
      en: 'Home Page + Mode Orchestration Redesign: One Page to Pick, Understand, Go',
    },
    summary: {
      zh: '把「未登入看 marketing 頁、登入後才看到節目」拆兩條路徑的舊設計，收成單一首頁：不管有沒有登入，一打開就看到完整節目清單，hero 區依登入狀態切換（marketing → 「嗨，XXX」+ 剩餘額度）。新增三模式介紹卡（索引 / 語意 / 對話），讓你在點進去之前心裡有底「這個模式適合什麼問題」。查詢頁從原本兩 tab 加上索引 tab（先佔位，backend 之後接），三 tab 順序固定，預設 tab 看登入狀態決定（登入→對話、未登入→索引）。Lock card 文案重寫：未登入版（🔒）只強調「不想花時間重聽找答案？」+ Google 登入按鈕；額度用完版（⏳）改寫成「申請更多次數」直接接到既有 modal，不再寫「重置時間」誤導使用者。對話 source 從「chip 列 + 卡片列」雙區整合成單一「答案參考來源（共 N 集 · M 段引用）」episode-grouped panel。語意結果改 flat list + 同集多段折成「+N 同集」chip + 相關度 bar。音訊播放器掛 router 外層跨頁不打斷（速度 1.0 / 1.25 / 1.5x，localStorage 記住）。逐字稿依停頓 ≥ 1.5 秒或講者變化自動聚段。',
      en: 'Merged the「marketing page if anon, show grid only after login」two-path design into a single Home Page: regardless of auth state, the full show list shows immediately; hero swaps (marketing → "Hi, XXX" + remaining quota). Three-mode educational card row added (Index / Semantic / Chat) so you know which mode fits which question before clicking. Query page got a third Index tab (placeholder; backend lands later); three tabs fixed order, default decided by auth state (signed-in→Chat, anon→Index). Lock card copy rewritten: anonymous (🔒) emphasizes "tired of re-listening?" + Google login; quota-exhausted (⏳) says "request more usage" and opens the existing modal, no longer claiming a "reset date" we never built. Chat source area consolidated into one episode-grouped panel "Answer sources (N episodes · M citations)". Semantic results render as flat RRF list with "+N in same episode" expand chips + relevance bar (no raw score). Audio player sits outside the router so navigation does not interrupt playback (speed 1.0 / 1.25 / 1.5x, persisted). Transcript aggregates segments into paragraphs by silence gap ≥ 1.5s or speaker change.',
    },
    summaryBullets: {
      zh: [
        '不論登入與否，首頁一打開就看到完整節目清單',
        '查詢頁新增第三個 tab「索引」（先佔位，backend 之後接）',
        'Lock card 文案重寫：不再寫「免費 N 次 / 重置時間」這類我們沒做的承諾',
        '對話 source 整合成單一 episode-grouped panel，同集多段不重複標題',
        '音訊播放器跨頁不打斷，速度 1.0/1.25/1.5x localStorage 記住',
        '逐字稿依停頓自動分段，比原本一句一句好讀',
      ],
      en: [
        'Home page shows the full show list immediately, signed-in or not',
        'Query page adds a third "Index" tab (placeholder; backend lands later)',
        'Lock card copy rewritten — no more "free N uses / reset date" claims we never delivered',
        'Chat source area consolidated into one episode-grouped panel',
        'Audio player survives navigation; speed 1.0/1.25/1.5x persisted',
        'Transcript view aggregates segments by silence gap — easier to read',
      ],
    },
  },
  {
    date: '2026-05-22', slug: 'retrieval-episode-reference-handling', milestone: 'v1.8', tag: 'enhancement',
    title: {
      zh: '問「EP134 講什麼？」現在真的回 EP134 內容了',
      en: '"What does EP134 talk about?" Now Actually Returns EP134 Content',
    },
    summary: {
      zh: '這版我們在跑回歸測試時抓到一個系統性問題：語意搜尋對「EP 134 講什麼？」這類「特定集數內容」的問題撈出來的段落經常不是 EP134 — 因為「EP134」這個字串在 episode 內文裡幾乎不會出現（內容是音樂、家常味、開工歌單⋯不是「EP134」三個字），embedding 跟 BM25 都沒辦法把問題對到正確段落。修法：在 `/search` endpoint 加一層 EP-reference 偵測，看到「EP134」這種 token 就把它轉成 episode UUID 再餵到 retrieval filter。chat agent 路徑早就有同等能力（agent 會主動呼 find_episode_by_ref tool），這次只是把 public 語意搜尋補齊。實測 Recall@5 從 0.23 拉到 0.42（+19pp），「EP134 開工歌單觀念」這類題目從 0 命中變 1.0 命中。',
      en: 'This release catches a systemic issue uncovered during regression testing: the semantic search endpoint frequently retrieves wrong-episode segments when the user asks "what does EP134 talk about?" — because the string "EP134" almost never appears verbatim in transcripts (content is about music, home cooking, work playlists... not "EP134" three characters), so neither embedding nor BM25 can map the question to the right chunks. Fix: added an EP-reference detection layer in `/search` endpoint that converts tokens like "EP134" into episode UUIDs and feeds them to the retrieval filter. The chat agent path already had equivalent capability (the agent proactively calls find_episode_by_ref), this release just brings the public semantic search up to parity. Measured Recall@5 jumped from 0.23 to 0.42 (+19pp); questions like "EP134\'s work playlist concept" went from 0 hit to 1.0 hit.',
    },
    summaryBullets: {
      zh: [
        '問「EP X」的特定集數題型，搜尋結果現在精準命中該集',
        'Recall@5 baseline 0.23 → 0.42（+19pp）',
        '只動 public search endpoint，chat 對話模式不變',
      ],
      en: [
        'Episode-specific questions ("EP X") now hit the right episode',
        'Recall@5 baseline 0.23 → 0.42 (+19pp)',
        'Only touches public search endpoint; chat mode unchanged',
      ],
    },
  },
  {
    date: '2026-05-22', slug: 'enable-agentic-chat-default-on', milestone: 'v1.8', tag: 'feature',
    title: {
      zh: 'Phase 2 翻牌：對話模式預設改用 AI 自主決策',
      en: 'Phase 2 Flip: Chat Mode Default Switched to AI-Driven Agent',
    },
    summary: {
      zh: '把 ENABLE_AGENTIC_CHAT 從「測試中」翻成預設開啟，所有人切到對話模式就直接走新的 AI agent loop（過去兩週 dogfood 同 30 題 0/30 看到「技術問題」訊號）。同場補一個容易漏的細節：agent 拿到節目跟段落資料後，原本沒把這些回填給前端 source 區，導致對話模式 source 卡片整個空白；現在從 agent 內部的 tool 結果撿出 chunk 跟 episode，回填給既有的「引用 chip」+「相關集數卡」兩塊區塊，使用者一打開就有完整資料呈現（UIX 細節後續另一個 change 接手優化）。Flag 留 30 天 kill-switch，若 prod 出問題可立即顯式翻回。同場補 LLM-as-judge 對 multi-turn-40 dataset 跑一輪當 quality gate 證據，並開兩個新 runbook（eval-pipeline / agentic-chat-observation）給後續 14 天觀察期值班參考。',
      en: 'Flipped ENABLE_AGENTIC_CHAT from "in testing" to default-on; everyone landing in chat mode now goes straight to the new AI agent loop (the last two weeks of dogfood ran the same 30-question set with 0/30 "technical issue" signal). Bundled fix for an easy-to-miss gap: after the agent finished its tool calls, the episode and chunk data was never mapped back to the frontend source panel, leaving the chat-mode source area completely blank. Now the response mapper collects chunks from search tools and episodes from listing/lookup tools and feeds the existing "citation chips" + "related episodes card" containers, so users see complete source info from day one (UIX polish is owned by a follow-up change). The flag stays as a 30-day kill-switch; explicit ENABLE_AGENTIC_CHAT=false still falls back to the rule-based pipeline. Also captured: LLM-as-judge against the multi-turn-40 dataset as the quality gate evidence, plus two new runbooks (eval-pipeline / agentic-chat-observation) for the 14-day observation-window on-call.',
    },
    summaryBullets: {
      zh: [
        '對話模式 default 翻 on：使用者打開就是新的 AI agent 行為',
        '補齊回應的 source 資料：紫色 chip + 集數卡兩塊區塊不再空白',
        '保留 30 天 flag kill-switch；prod 出問題顯式翻回 false 立即生效',
        'LLM-as-judge 對 40 題 multi-turn 跑一輪當 gate 證據（answer_match +2.7pp）',
        '同場開兩個 runbook：eval pipeline 全圖 + 14 天觀察期值班 SOP',
      ],
      en: [
        'Chat-mode default flipped on — landing in chat mode now goes straight to the AI agent',
        'Source data mapped back: purple chips + episode cards no longer blank in chat mode',
        '30-day flag kill-switch retained; explicit ENABLE_AGENTIC_CHAT=false still works as a fallback',
        'LLM-as-judge against 40-turn multi-turn dataset as gate evidence (answer_match +2.7pp)',
        'Two new runbooks: eval pipeline overview + 14-day observation-window SOP',
      ],
    },
  },
  {
    date: '2026-05-22', slug: 'chat-tool-error-isolation', milestone: 'v1.8', tag: 'fix',
    title: {
      zh: '對話模式錯誤訊息變友善了',
      en: 'Chat Mode: Error Messages Got Friendlier',
    },
    summary: {
      zh: '上週開始 dogfood 對話模式時，偶爾會撞到「系統查詢時遇到了技術問題」這種 user 體感超差的回覆——我們追了完整 trace 之後發現是內部資料庫某個欄位名拼錯了，AI 工具呼叫失敗後又把原始錯誤訊息（含內部 exception 名稱）直接翻給 user。這版三層一起修：修了拼錯的 SQL、AI 每呼一個工具用 SAVEPOINT 隔離（一個工具炸不會連坐後續工具）、加上結構化錯誤格式 `{ok, kind, internal_message, user_hint}` 讓 AI 看 `kind` 判斷下一步、user 視角只看 `user_hint`，並且在 system prompt 明文禁止 AI 輸出內部錯誤類別名或「技術問題」這種字眼。修完同樣 30 題 dogfood，「技術問題」訊號從 1/30 降到 0/30；Phase 2 翻 default 前最後一個 blocker 清掉了。',
      en: 'When we started dogfooding chat mode last week, the bot occasionally replied "the system encountered a technical issue during the query" — terrible UX. Full trace investigation traced it to: an internal column-name typo in one SQL, AI tool failure then leaked the raw exception class name to the user. This release fixes all three layers: corrected the SQL typo, wrapped every tool call in a SAVEPOINT so one tool failing does not cascade into the next, and introduced a structured error envelope `{ok, kind, internal_message, user_hint}` where AI uses `kind` for routing decisions and users only see `user_hint`. The system prompt now explicitly forbids leaking internal exception class names or "technical issue"-style phrasings. After the fix, the same 30-question dogfood run showed "technical issue" signals drop from 1/30 to 0/30; the last blocker for flipping the Phase 2 default is cleared.',
    },
    summaryBullets: {
      zh: [
        '使用者不會再看到「系統查詢時遇到了技術問題」這種裸露的內部錯誤訊息',
        'AI 每呼一個工具用 SAVEPOINT 隔離，一個工具撞 bug 不會把後續工具都拖下水',
        '錯誤訊息改成結構化格式：AI 看 kind 決定怎麼處理、user 看 user_hint',
        'dogfood 30 題 failure signal 從 1/30 降到 0/30',
      ],
      en: [
        'Users no longer see raw "the system encountered a technical issue" messages',
        'Every tool call is now SAVEPOINT-isolated — one tool failing does not cascade into the next',
        'Error format restructured: AI reads `kind` to decide next steps; user only sees `user_hint`',
        '30-question dogfood failure-signal rate dropped from 1/30 to 0/30',
      ],
    },
  },
  {
    date: '2026-05-21', slug: 'agent-trace-telemetry', milestone: 'v1.8', tag: 'enhancement',
    title: {
      zh: '對話模式裝上「黑盒紀錄器」協助除錯',
      en: 'Chat Mode Gains a Black-Box Recorder for Debugging',
    },
    summary: {
      zh: '對話模式翻 default 前的觀測投資——把 AI 每一輪 LLM 呼叫的 latency 與 token、每個工具呼叫的參數與結果、各階段時間花在哪裡，全部結構化記錄成 trace 留下來；admin 帶 `?debug_trace=true` 才看得到完整內容，一般使用者回應形狀不變。同場補一支 `dogfood_trace_dump.py` 把 30 題對話批次跑完落盤，這份 trace 立刻派上用場：抓到 q03「45 歲開工歌觀點」失敗的真正原因是一個內部 SQL column 名拼錯——直接催生隔天的 chat-tool-error-isolation 修復。',
      en: 'Observability investment before flipping the chat-mode default. Every per-round LLM call (latency, tokens), every tool dispatch (name, args, result), and every stage timing now ships as a structured trace. Admins see the full payload by appending `?debug_trace=true`; regular users see no change in response shape. Bundled with a `dogfood_trace_dump.py` script that batches 30 questions into a saved trace dump — which immediately paid off: it traced q03 ("45-year-old work-song views") down to a single misspelled SQL column name, directly triggering the next-day chat-tool-error-isolation fix.',
    },
    summaryBullets: {
      zh: [
        '每輪 LLM 呼叫、每個工具呼叫、每個階段時間都有結構化 trace',
        'admin 帶 `?debug_trace=true` 看完整 trace；一般使用者不受影響',
        '`dogfood_trace_dump.py` 批次跑完落盤，幫忙抓到一個關鍵 SQL bug',
      ],
      en: [
        'Per-round LLM calls, per-tool dispatches, and per-stage timings are all structured into trace',
        'Admins see the full trace via `?debug_trace=true`; regular users see no change',
        '`dogfood_trace_dump.py` batches a dump; helped trace a critical SQL bug to its root',
      ],
    },
  },
  {
    date: '2026-05-21', slug: 'chat-agentic-tool-routing', milestone: 'v1.8', tag: 'feature',
    title: {
      zh: '對話模式升級：AI 自己決定要查什麼、查幾次',
      en: 'Chat Mode Upgraded: AI Decides What to Look Up and How Many Times',
    },
    summary: {
      zh: '之前的對話模式走「先嵌入向量、做混合檢索、再讓 LLM 寫答案」的固定流程，不管問題長什麼樣都是同一條 pipeline；遇到「歌單有哪幾集？」「第三集講什麼？」這種要分兩步看的問題就常常卡住。這版改成 agent loop：AI 拿到問題後自己決定要呼哪個 tool（找節目、找來賓、找日期、查摘要、查段落、show 概覽、pin/unpin 集數…11 個 callable），可以連續呼叫多次直到湊到夠的資訊再回答。順手修了「先列舉再用序數」（你問「歌單有哪幾集？」之後追問「第三集講什麼？」）的多輪 carry bug — 之前三套主流 agent 框架測試都跟丟，這版用 system prompt 教 LLM 對應到上一輪列舉結果的第三筆 ep_id。目前 feature flag 預設關閉，先自己 dogfood 兩週、跑 eval 比對通過後才會翻 default。',
      en: 'The previous chat mode ran a fixed pipeline (embed → hybrid retrieval → LLM writes answer) regardless of the question — so multi-step questions like "Which episodes have playlists?" → "What\'s episode 3 about?" often broke. This release switches to an agent loop: the AI receives the question and decides which tool to call (find by topic / guest / date, get episode summary, get segments, show overview, pin/unpin episode… 11 callables total), can chain multiple calls until it has enough info, then answers. Also fixed the "enumerate then ordinal reference" multi-turn carry bug — all three major agent frameworks failed this in our bake-off, but a system-prompt instruction mapping "the third episode" to the previous enumeration\'s [N-1] ep_id resolves it cleanly. Feature flag is OFF by default for now — self-dogfood two weeks, run the eval gate, then flip default.',
    },
    summaryBullets: {
      zh: [
        '對話模式從固定 pipeline 改成 agent 自己呼 tool，可連續呼叫直到資訊足夠',
        '11 個 tool 涵蓋：找節目（topic / guest / date / ref）、查摘要 / 段落、show 概覽、pin/unpin 集數',
        '修了「歌單有哪幾集？→ 第三集講什麼？」多輪追問 bug（bake-off 三套框架都跟丟）',
        '目前 feature flag 預設關閉，先 dogfood 兩週、跑 eval gate 通過才翻 default',
      ],
      en: [
        'Chat mode switched from fixed pipeline to agent-driven tool calls; can chain multiple calls until satisfied',
        '11 tools cover: finding episodes (topic / guest / date / ref), getting summary / segments, show overview, pin/unpin episodes',
        'Fixed multi-turn "enumerate then ordinal" bug ("Which episodes have playlists?" → "What\'s episode 3 about?") that broke all three frameworks in our bake-off',
        'Feature flag is OFF by default — two weeks of dogfood + eval gate must pass before flipping the default',
      ],
    },
  },
  // ─── v1.7 — Retrieval Quality Fix (5/13–5/19) ───
  {
    date: '2026-05-19', slug: 'celery-publish-routing-fix-and-f2-smoke', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '外部服務告警系統補上兩個 silent drop 漏洞',
      en: 'Fixed Two Silent-Drop Bugs Holding Back the Outage Alert System',
    },
    summary: {
      zh: '前一版 ship 的「外部服務出問題自動暫停 + 寄信通知」(circuit breaker) 跑 prod smoke 時抓到兩個 silent drop bug：(1) 後台「重新生成摘要」按鈕回 200 enqueued=true，但 Celery worker 其實沒收到任務 — 原因是 FastAPI 的 async 路由直接呼叫 sync 的 Celery publisher，跟 asyncpg event loop 衝突；(2) worker 真的接到失敗任務後，本來要寫進 task_failure_log 表的 async coroutine 因為 worker 殘留的 closed event loop 沒被執行 → 失敗計數永遠是 0 → circuit 永遠不會自動 open → 告警信永遠不會寄。兩個 bug 都是把 async/sync 接合改用獨立的 thread + 新 event loop 隔離解掉。順手把 F1 殘留的 cron_tick 任務跑去 default queue 的 leak（beat schedule 沒指定 queue）一起補。實測：拿一把假 aihub key 灌 5 個摘要任務 → 90 秒內後台「服務狀態」aihub 變紅、出現「手動恢復」按鈕、點完按鈕後馬上變綠 + 出現「已手動恢復」提示。',
      en: 'After the previous "external service auto-pause + email alert" (circuit breaker) shipped, prod smoke caught two silent-drop bugs: (1) the admin "regenerate summary" button returned 200 enqueued=true, but the Celery worker never actually received the task — caused by FastAPI\'s async route directly calling the sync Celery publisher, conflicting with the asyncpg event loop; (2) once a worker did receive a failing task, the async coroutine that should write to task_failure_log silently dropped because of the worker\'s residual closed event loop after task crash → failure count stayed at 0 → circuit never opened → alert email never sent. Both fixed by isolating the async/sync boundary into a dedicated thread with a fresh event loop. Also patched the F1 leftover where cron_tick leaked to the default queue (beat schedule entries missing options.queue). Verified end-to-end: feeding 5 summary tasks to a fake aihub key → within 90 seconds the admin Service Status page shows aihub as red with a "Manual Resume" button → clicking it flips back to green with a "Manually Resumed" toast.',
    },
    summaryBullets: {
      zh: [
        '後台「重新生成摘要」publish 從 silent drop 變成 fail-loud 503',
        '失敗記錄與 circuit breaker 真的會在外部服務掛掉時自動 open',
        '後台「服務狀態」分頁可看到紅綠狀態跟「手動恢復」按鈕',
        'F1 cron_tick leak 一起補（beat schedule 顯式指定 control queue）',
      ],
      en: [
        'Admin "regenerate summary" publish flipped from silent drop to fail-loud 503',
        'Failure logging + circuit breaker now actually open when an external service goes down',
        'Service Status admin tab shows green/red badges + "Manual Resume" button',
        'Bundled fix for F1 cron_tick leak (beat schedule now explicitly routes to control queue)',
      ],
    },
  },
  {
    date: '2026-05-19', slug: 'task-failure-monitoring-and-circuit-breaker', milestone: 'v1.7', tag: 'feature',
    title: {
      zh: '外部 LLM / 寄信服務出問題會自動暫停 + 寄信通知',
      en: 'External LLM / Email Service Outage Auto-Pause + Email Notification',
    },
    summary: {
      zh: '建立後端任務失敗監控 + circuit breaker：當 aihub / openai / zsend 任一外部服務在 5 分鐘內失敗超過閾值，自動把該服務的 circuit「open」、後續任務自動暫停 5 分鐘再 retry（不會 worker 一直空轉燒 quota），同時寄一封 ZSend 告警信通知 admin。每 30 分鐘自動探測一次外部服務、通則就自動恢復；也可在後台「服務狀態」分頁手動點「恢復」按鈕（會收到 recovery 信）。後台 admin 新增「服務狀態」分頁列出三個外部 provider 的當前狀態（綠/紅 badge + 暫停起時 + 影響任務數 + 最後探測時間 + 手動恢復按鈕）。失敗事件全部寫進新表 `task_failure_log` 留歷史紀錄。這版同時把 5/10 凌晨同日抓到的「EP2 transcribe 連續失敗無人察覺」「topic backfill 批次全失敗沒 alert」兩個 silent failure 漏洞補上。',
      en: 'Built backend task failure monitoring + circuit breaker: when any external service (aihub / openai / zsend) fails more than the threshold within a 5-minute window, the breaker automatically "opens" for that service, subsequent tasks self-pause for 5 minutes and retry (no busy-spinning that burns quota), and a ZSend alert email goes out to admin. The system auto-probes every 30 minutes and recovers when the service responds; admin can also click "Manual Resume" in the Service Status tab (which sends a recovery email). Adds a new "Service Status" admin tab showing the three external providers\' current state (green/red badge + paused-since + affected task count + last probe + manual resume button). All failure events are recorded in a new `task_failure_log` table for historical reference. This release also closes the two silent-failure gaps caught on 5/10 morning ("EP2 transcribe failed repeatedly with nobody noticing" and "topic backfill batch all failed with no alert").',
    },
    summaryBullets: {
      zh: [
        '外部服務失敗超閾值自動暫停 + 寄信告警，不再 silent 燒 quota',
        '後台「服務狀態」分頁可看綠/紅 badge + 暫停起時 + 一鍵手動恢復',
        '每 30 分鐘自動探測，外部服務恢復後自動 close',
        '全部失敗事件落 `task_failure_log` 表留歷史',
      ],
      en: [
        'External service failures over threshold auto-pause + alert email — no more silent quota burn',
        'Service Status admin tab shows green/red badge + paused-since + one-click manual resume',
        'Auto-probes every 30 minutes, breaker auto-closes when service recovers',
        'All failure events recorded in `task_failure_log` for history',
      ],
    },
  },
  {
    date: '2026-05-18', slug: 'celery-routing-and-dispatcher-fix', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '新節目轉錄永遠優先處理，不再被 batch 任務堵',
      en: 'New Episode Transcription Always First, No Longer Blocked by Batch Backfills',
    },
    summary: {
      zh: '5/10 發現 EP20（Axios 那集）排在轉錄佇列裡 9 個多小時沒被處理 — 因為當時前面排著 100 個 topic 補跑任務，後端只有一個 worker 全部一個一個吃完才輪到。這版把後端任務分四條 queue（轉錄 / topic / 摘要 / 控制）並設優先級：轉錄任務 priority=9（最高）、topic / 摘要 priority=2（最低）、其他控制類 priority=5。同一個 worker 同時訂閱四條 queue，broker 按優先級 pop — 新節目進來不管前面排多少 topic 都會被先抽出來。另外 dispatcher 加 `dispatched_at` 欄位 + `FOR UPDATE SKIP LOCKED`，徹底解掉「同一筆連發兩個 Celery 任務」的競態 bug。Prod 已驗 dispatcher 新 schema 跑通、worker 訂閱四條 queue 且優先級設定正確。',
      en: 'On 5/10 we found EP20 (the Axios episode) sat in the transcription queue for 9+ hours unprocessed — 100 topic backfill tasks were queued ahead and the single worker chewed through them one by one. This release splits backend tasks into four queues (transcribe / topic / summary / control) with priorities: transcribe at priority=9 (highest), topic/summary at priority=2 (lowest), control defaults at priority=5. The same worker subscribes to all four queues; the broker pops by priority, so new episodes get pulled ahead regardless of how many topic tasks are queued. The dispatcher also gained a `dispatched_at` column + `FOR UPDATE SKIP LOCKED` to eliminate the race where the same row could be dispatched twice. Prod verified: dispatcher running the new schema, worker subscribed to four queues with correct priority binding.',
    },
    summaryBullets: {
      zh: [
        '轉錄優先級拉到最高（priority=9），topic / 摘要降到最低（priority=2）',
        '新節目轉錄永遠優先 pick，不會排在 topic 補跑任務後面',
        'Dispatcher 加 `dispatched_at` + `FOR UPDATE SKIP LOCKED` 解雙派 race',
        'Worker 啟動時自動 reset 卡 running 又沒實際在跑的 row 回 pending',
      ],
      en: [
        'Transcription priority raised to top (priority=9), topic / summary dropped to lowest (priority=2)',
        'New-episode transcription always picked first, never queued behind topic backfills',
        'Dispatcher gained `dispatched_at` + `FOR UPDATE SKIP LOCKED` to fix double-dispatch race',
        'Worker startup auto-resets rows stuck at running-without-actual-execution back to pending',
      ],
    },
  },
  {
    date: '2026-05-18', slug: 'citation-display-unify', milestone: 'v1.7', tag: 'ui',
    title: {
      zh: '對話模式的引用區塊重整，列舉題集數卡跟段落引用不再並排',
      en: 'Chat Citation Layout: Episode Cards and Excerpts No Longer Side-by-Side',
    },
    summary: {
      zh: '之前在對話模式問「歌單哪幾集」「馬世芳上過哪幾集」這類列舉題，答案上方會出現一張一張的集數卡（episode card），下方又會出現紫色 chunk 段落 chip — 同一集可能在兩處都出現，使用者不容易看出兩者差異（卡片點開整集、chip 跳到該段秒數）。這版改為主從佈局：列舉題時集數卡放主視覺、底下「為什麼這幾集被選 (N 個段落)」摺疊區預設收起、展開後才看得到 chunk chips；單純內容題（例如「EP143 講了什麼」）沒有列舉就維持原本的 chip inline 渲染。三題 sample 視覺驗證完整通過 — 列舉題、內容題、topic-trigger（單獨打「歌單」） 都正確。',
      en: 'Previously, asking enumeration questions in chat ("which episodes have guest X", "which episodes are music playlists") would show episode cards above the answer AND chunk chips below — the same episode could appear in both places, with no visual cue about the difference (card opens the full episode, chip jumps to a specific second). This release adopts a main+supporting layout: enumeration questions render episode cards as the primary visualization, with a collapsible "Why these episodes (N excerpts)" section below that defaults to collapsed and reveals the chunk chips when expanded. Content questions (e.g. "what did EP143 discuss") without enumeration keep the original inline chip rendering. Three sample queries visually verified end-to-end — enumeration, content, and topic-trigger ("playlist" alone) all render correctly.',
    },
    summaryBullets: {
      zh: [
        '列舉題：上方集數卡為主視覺、下方「為什麼這幾集被選 (N 個段落)」摺疊區預設收起',
        '內容題（enum 為空）：完全維持原本 chip inline 渲染、無摺疊',
        '展開摺疊後點 chip 仍正確觸發 citation_click event 跟跳秒導航',
        '中英雙語：zh `為什麼這幾集被選 (N 個段落)` / en `Why these episodes (N excerpts)`',
      ],
      en: [
        'Enumeration: episode cards as primary, collapsible "Why these episodes (N excerpts)" defaults to collapsed below',
        'Content (empty enum): original inline chip rendering unchanged, no collapse',
        'Citation_click event and timestamp-jump navigation work correctly after expanding',
        'i18n: zh `為什麼這幾集被選 (N 個段落)` / en `Why these episodes (N excerpts)`',
      ],
    },
  },
  {
    date: '2026-05-18', slug: 'disabled-user-appeal-flow', milestone: 'v1.7', tag: 'feature',
    title: {
      zh: '帳號被停權時有正式申訴入口，不再是死路',
      en: 'Disabled Accounts Now Have a Formal Appeal Channel',
    },
    summary: {
      zh: '之前如果某個帳號被加進黑名單，使用者走 Google 登入後會收到 403 錯誤，前端只顯示一行「無法登入」就結束 — 沒有任何申訴管道，只能私訊管理員。這版加了正式申訴流程：OAuth callback 拒絕 disabled 帳號時改 redirect 回首頁帶 `?auth_error=account_disabled&appeal_enabled=true&email=...` 參數（不直接吐 403 JSON 把瀏覽器搞爆），SPA 偵測到參數後渲染 Lock card 第三狀態（🚫 icon + 「提出申訴」按鈕）→ 點開申訴 Modal 填事由（1-2000 字、自動帶 email、IP 每日限 5 次）→ 後端寫進新表 `account_appeals` → 每日台北 09:00 cron 寄 digest email 給 admin。後端三道防線：reason 空白 / 超 2000 字回 400；unknown email 與 active user email 為防列舉攻擊都靜默回 accepted 但不寫表；同 IP 每日第 6 次 429。所有 admin 行為走既有 ZSend email 不開新後台 UI（MVP），未來有量再開審核 dashboard。',
      en: 'Previously, when an account got blacklisted, the user would hit a 403 error after Google login and the frontend just showed a one-line "cannot log in" — no appeal channel, just a dead end. This release adds a formal appeal flow: when the OAuth callback rejects a disabled account, it now redirects back to the home page with `?auth_error=account_disabled&appeal_enabled=true&email=...` query params (instead of returning raw 403 JSON which would break the SPA). The SPA detects the params and renders the Lock card third state (🚫 icon + "Submit Appeal" button) → clicking opens the Appeal Modal with a reason textarea (1-2000 chars, auto-fills email, IP rate-limited 5/day) → backend writes to the new `account_appeals` table → a daily 09:00 Taipei cron sends a digest email to admins. Backend has three defenses: empty/over-2000 reason returns 400; unknown email and active-user email both silently return accepted without writing to the DB (to prevent account enumeration); 6th request from the same IP per day returns 429. Admin handling uses existing ZSend email; no new admin UI in MVP — a review dashboard ships later if volume justifies it.',
    },
    summaryBullets: {
      zh: [
        'OAuth callback 對 disabled 帳號改 redirect `?auth_error=account_disabled&appeal_enabled=...&email=...`，不直接吐 403 JSON 破壞 SPA',
        'Lock card 加第三狀態 disabled（🚫 icon + 申訴 CTA）+ 新 AppealModal（reason textarea 1-2000 字、auto-fill email）',
        '新表 `account_appeals` + 每日 09:00 台北 digest email 寄給 admin',
        '反濫用：unknown email / active user 都靜默 accepted 不寫表（防列舉攻擊）；同 IP 每日 5 次後 429',
      ],
      en: [
        'OAuth callback for disabled accounts redirects to `?auth_error=account_disabled&appeal_enabled=...&email=...` instead of returning raw 403 JSON (which would break the SPA)',
        'Lock card gains third state disabled (🚫 icon + appeal CTA) + new AppealModal (reason textarea 1-2000 chars, auto-fills email)',
        'New `account_appeals` table + daily 09:00 Taipei digest email to admins',
        'Anti-abuse: unknown email / active user silently return accepted without writing to DB (prevents enumeration); 6th IP-request per day returns 429',
      ],
    },
  },
  {
    date: '2026-05-18', slug: 'aihub-graphql-adapter-migration', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '後台 AI Hub 用量數字之前一直顯示 0，現在已可正常追蹤實際花費',
      en: 'AI Hub Usage Now Tracked Correctly (Previously Always 0)',
    },
    summary: {
      zh: '上一版「服務用量」分頁的 AI Hub 那一欄之所以空白，是因為 collector 對著一個不存在的網址 `aihub.zeabur.app/v1/usage` 打 — 那是當初寫程式時憑感覺猜的 URL，從 2026-05-09 上線後整整 9 天都沒人發現 DB 裡 aihub provider 連一筆 row 都沒寫進去。這版改走 Zeabur 官方 GraphQL endpoint (`api.zeabur.com/graphql`) 的 `aihubMonthlyUsage` query，schema 直接從 zeabur/ai-sdk 公開 repo 取出，本機 curl 驗過 totalSpend $77.54 與 CLI `zeabur ai-hub status` 顯示完全吻合。adapter 跨月 range 會自動拆成多次 query、超過 6 個月 raise，5xx 改回 raise 不再 fail-open（信任 Zeabur SLA），4xx 立即 raise。Prod 觸發一輪 collector 後 aihub row 直接寫進 DB、admin 後台看得到實際花費數字。同場補一條工程紀律：未來寫 adapter 一定要先 curl 證明 endpoint 真的活著、或查官方 SDK schema，不能用感覺猜。',
      en: 'In the previous release, the "Service Usage" tab\'s AI Hub column was blank because the collector pointed at a non-existent URL `aihub.zeabur.app/v1/usage` — a guessed URL from when the code was first written. For 9 days after the 2026-05-09 launch, nobody noticed that not a single aihub provider row had been written to the DB. This release switches to Zeabur\'s official GraphQL endpoint (`api.zeabur.com/graphql`) using the `aihubMonthlyUsage` query, schema pulled directly from zeabur/ai-sdk public repo. Local curl verified totalSpend $77.54 matches `zeabur ai-hub status` exactly. The adapter auto-splits cross-month date ranges into per-month queries, raises ValueError beyond 6 months, raises on 5xx after retries (trust Zeabur SLA, no more fail-open), and raises immediately on 4xx. After triggering one collector cycle in prod, aihub rows landed in the DB and the admin tab now shows real spend. Engineering discipline added: always curl-verify an endpoint or check the official SDK schema before writing an adapter — no more guessing URLs.',
    },
    summaryBullets: {
      zh: [
        'AI Hub adapter 從猜測 REST endpoint 改走官方 GraphQL `aihubMonthlyUsage` query — schema 從 zeabur/ai-sdk repo 取',
        '本機 curl 驗證 totalSpend $77.54 與 `zeabur ai-hub status` 完全吻合，prod 觸發 collector 後 admin 看得到真實數字',
        '5xx 改回 raise（不再 fail-open）— 信任 Zeabur SLA，沉默失敗比噪音危險',
        '工程紀律：未來寫外部 adapter 一律先 curl 驗 endpoint 或查官方 SDK，不能憑感覺猜 URL',
      ],
      en: [
        'AI Hub adapter switched from guessed REST endpoint to official GraphQL `aihubMonthlyUsage` query — schema from zeabur/ai-sdk repo',
        'Local curl verified totalSpend $77.54 matches `zeabur ai-hub status` exactly; admin tab shows real numbers after one prod collector cycle',
        '5xx now raises (no more fail-open) — trust Zeabur SLA; silent failure is more dangerous than noise',
        'Engineering discipline: always curl-verify an endpoint or check the official SDK before writing an adapter — no more guessed URLs',
      ],
    },
  },
  {
    date: '2026-05-18', slug: 'multi-provider-usage-monitoring', milestone: 'v1.7', tag: 'enhancement',
    title: {
      zh: '後台多了「服務用量」分頁，看 OpenAI 月花費 + 預算超標自動寄信告警',
      en: 'Admin Gets "Service Usage" Tab — OpenAI Monthly Spend + Auto Budget Alerts',
    },
    summary: {
      zh: '以前 admin 要知道這個月在 OpenAI 跟 Zeabur AI Hub 上燒了多少錢，得分別開兩個外部後台手動翻。這版在後台多了「服務用量」分頁：上方雙 banner（黃色 ≥ 80%、紅色 ≥ 95%）即時顯示每個 provider 累積花費 vs 預算（v1 hardcoded：AI Hub $80 / OpenAI $30），下面是 30 天 stacked bar chart 視覺化日支出。每天台北 09:00 跑 alert worker，達 80% / 95% 自動寄信告警（per-day 去重不洗信箱）。OpenAI 那邊接通了直接從官方 organization/costs API 拉資料；AI Hub 那邊本來打算抓 `aihub.zeabur.app/v1/usage`，但發現是猜錯的 endpoint（正確是 Zeabur GraphQL `aihubMonthlyUsage`），所以這版 AI Hub 那一欄會空白、collector 走 fail-open 不阻塞 OpenAI 寫入，AI Hub 真實接入會在下個 follow-up change 補完。同場加映：每次 commit 前都會 gitleaks 掃 secret 不會把 key 寫進歷史。',
      en: 'Previously, to know how much was spent on OpenAI and Zeabur AI Hub this month, admins had to open two separate external dashboards. This release adds a "Service Usage" tab: dual banners at the top (yellow ≥ 80%, red ≥ 95%) showing per-provider monthly spend vs budget (v1 hardcoded: AI Hub $80 / OpenAI $30), with a 30-day stacked bar chart below. An alert worker runs daily at 09:00 Taipei and sends email alerts at 80% / 95% thresholds (deduped per day so the inbox stays sane). OpenAI is fully wired up via the organization/costs API; AI Hub was initially pointed at `aihub.zeabur.app/v1/usage` which turned out to be a guessed endpoint that does not exist (the correct one is Zeabur GraphQL `aihubMonthlyUsage`), so AI Hub column will be blank in this version and the collector now fail-opens on 5xx/timeout instead of polluting alerts. The AI Hub real wiring lands in a follow-up change.',
    },
    summaryBullets: {
      zh: [
        '後台「服務用量」分頁：黃 80% / 紅 95% 兩級 banner + 30 天日花費 stacked bar chart（純 inline SVG，沒裝 chart 套件）',
        'OpenAI 走 `organization/costs` API 自動每小時抓一次，admin 可即時看到月累積',
        '達 80% / 95% 預算門檻會寄信告警（每天 09:00 台北跑、per-day 去重）',
        'AI Hub adapter 改 fail-open：5xx / timeout 直接 skip 不阻塞 collector；真實接入待 follow-up change 用 GraphQL 重做',
      ],
      en: [
        '"Service Usage" admin tab: yellow 80% / red 95% banners + 30-day stacked bar chart of daily spend (pure inline SVG, no chart library added)',
        'OpenAI auto-collected hourly via `organization/costs` API; admins see running monthly total',
        '80% / 95% budget thresholds trigger email alerts (runs daily 09:00 Taipei, deduped per day)',
        'AI Hub adapter now fail-opens on 5xx/timeout — does not block the rest of the collector; real wiring lands in a follow-up via Zeabur GraphQL',
      ],
    },
  },
  {
    date: '2026-05-18', slug: 'backfill-progress-admin-tab', milestone: 'v1.7', tag: 'enhancement',
    title: {
      zh: '後台 Queue 分頁上方多了「進度概覽」，一眼看出轉錄／摘要／分類做到哪',
      en: 'Admin Queue Tab Gains "Processing Overview" — See Transcription / Summary / Topic Progress at a Glance',
    },
    summary: {
      zh: '以前要知道「現在所有節目轉錄到第幾集了、AI 摘要補到哪、主題分類進度多少」，得自己下 SQL 或翻 log。這版在後台 Queue 分頁最上方加了「進度概覽」區塊：三條 progress bar 分別顯示轉錄、AI 摘要、主題分類的完成比例（分母是已 publish 的集數），下面再給最近 24 小時的新增量跟失敗任務數，需要時可展開看失敗的 task 名稱跟錯誤訊息範例。整塊每 30 秒自動更新一次，網路斷掉會顯示「更新失敗，重試中」但不影響底下原本的 queue 排程表。對 admin 來說，平常巡視一眼就知道 backfill 進度健不健康，不用再開 DB query。',
      en: 'Previously, checking "how many episodes are transcribed across all shows, how many have AI summaries, how far along is topic classification" required ad-hoc SQL or log spelunking. This release adds a "Processing Overview" panel at the top of the admin Queue tab: three progress bars for transcription, AI summary, and topic classification (denominator = published episodes), plus a Last-24-Hours section showing newly-completed counts and any failed tasks, with an expandable view for task name + sample error message. Refreshes every 30 seconds; on network failure it shows a soft "Refresh failed, retrying" warning without disrupting the queue table below. Admins now get health-at-a-glance for backfill progress without opening a DB client.',
    },
    summaryBullets: {
      zh: [
        '新 endpoint `GET /admin/processing-stats`：admin role gate + CSRF，回傳轉錄／摘要／topic_seg 三維度的 episode/segment count 與 24h 變化、失敗統計',
        '前端 `<ProcessingOverview>` 子元件接在 QueueTab 最上方，純 CSS progress bar，沒裝新 chart 套件',
        '30 秒 polling，斷網時顯示警告 text 但不影響底下 queue 表',
        '失敗清單可展開看 task_name × count × sample_error，方便快速 triage',
      ],
      en: [
        'New `GET /admin/processing-stats` endpoint (admin role gate + CSRF) returns episode/segment counts, 24h deltas, and failure stats across transcription / summary / topic_seg dimensions',
        'New `<ProcessingOverview>` component renders at the top of the Queue tab — pure-CSS progress bars, no new chart library added',
        '30s polling with a soft "Refresh failed, retrying" warning on network errors that does not disrupt the queue table below',
        'Expandable failure list shows task_name × count × sample_error for quick triage',
      ],
    },
  },
  {
    date: '2026-05-18', slug: 'whisper-chunking-fix', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '修掉長集（>22 MB）轉錄會悄悄 retry 到 fail 的 bug，並加上明確錯誤訊息',
      en: 'Fix Long Episodes (>22 MB) Silently Retrying to Failure — Now With Explicit Errors',
    },
    summary: {
      zh: '之前 prod 觀察到 EP20（Axios 80 分鐘集，26.3 MB）跟其他 4-5 個大檔卡住：worker 把整檔送進 OpenAI Whisper API、被 25 MiB 上限退回 HTTP 413、然後反覆 retry，每輪燒掉一個 worker slot ~30 秒，最後 MaxRetries 失敗。表面上看 chunking 設定（`OPENAI_WHISPER_CHUNK_SIZE_MB=22`）有開但 split 邏輯沒被走到。這版加了兩道防線：(1) `RemoteAudioPathError` — `_transcribe_sync` 一偵測到 audio_path 是 R2 URL 而非本地檔就立刻 raise，worker 層 catch 再重新下載成 temp 檔，徹底防 path resolution 漏掉的情況；(2) `OversizedAudioError` — 上傳前 + 每個 chunk 上傳前都 hard guard 25 MiB，超過直接 raise 明確 exception，不再 silent 413 燒 retry。再加 3 條 unit test 鎖住 chunking 真的會 fire、超過上限會擋、URL path 會擋三條 path。EP57（96.85 分鐘，比 EP20 還長）2026-05-17 跑只用了 8 分 5 秒完整轉錄、3414 段覆蓋整段音檔，間接證實 chunking 已就位。',
      en: 'Earlier in prod, EP20 (Axios 80-min episode, 26.3 MB) and 4-5 other large files got stuck: the worker uploaded the whole file to OpenAI Whisper, hit the 25 MiB ceiling with HTTP 413, and retried in a loop — each retry burned a worker slot ~30s before eventually failing with MaxRetries. Chunking was configured (`OPENAI_WHISPER_CHUNK_SIZE_MB=22`) but the split branch was never reached. This release adds two defensive guards: (1) `RemoteAudioPathError` — `_transcribe_sync` raises immediately if `audio_path` looks like an R2 URL instead of a local file; worker layer catches and re-downloads to a temp file, eliminating the path-resolution gap; (2) `OversizedAudioError` — hard 25 MiB guard before the initial upload AND before every chunk upload; oversized files raise an explicit exception instead of silently 413-looping. Three new unit tests lock in that chunking actually fires, oversized files are rejected, and URL paths are rejected. EP57 (96.85 minutes, longer than EP20) ran on 2026-05-17 in 8 min 5 sec end-to-end, producing 3414 segments covering the full audio — strong indirect evidence chunking is now in place.',
    },
    summaryBullets: {
      zh: [
        '加 `RemoteAudioPathError`：偵測 audio_path 非本地檔直接 raise，worker 重下載成 temp 檔',
        '加 `OversizedAudioError`：上傳前 + 每 chunk 25 MiB hard guard，不再 silent 413',
        'INFO log `decision=chunked chunks=N` 進場印出，方便日後 triage',
        '3 條 unit test：chunking fire / oversized reject / remote URL reject',
        '間接驗證：EP57（96.85 分鐘）8 分 5 秒跑完、3414 段完整覆蓋；直接 log 因 worker 6hr retention 沒搶到原文',
      ],
      en: [
        'Added `RemoteAudioPathError` — non-local audio_path raises immediately; worker re-downloads to local temp file',
        'Added `OversizedAudioError` — hard 25 MiB guard before initial upload AND before every chunk; no more silent 413 retry loops',
        'INFO log `decision=chunked chunks=N` at entry for future triage visibility',
        '3 unit tests: chunking fires / oversized rejected / remote URL rejected',
        'Indirect verification: EP57 (96.85 min) transcribed end-to-end in 8m 5s, 3414 segments covering full audio; direct log line not captured due to 6hr worker log retention',
      ],
    },
  },
  // ─── v1.7 — Retrieval Quality Fix (5/13–5/17) ───
  {
    date: '2026-05-17', slug: 'fix-eval-dataset-com-004-json-leak', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '修掉答案偶爾長得像 `{"answer":"..."}` 這種亂碼的小 bug',
      en: 'Fix Occasional Self-Referential JSON Wrapper in Chat Answers',
    },
    summary: {
      zh: '對話模式偶爾會回出長得像 `{"answer":"真正的答案在這裡"}` 這種亂碼字串，前端看起來像 LLM 故障、判分 judge 也會誤判（R2.1 RCA 抓到 thisno-core-com-004 那題就是這個原因）。根因：LLM 回傳的 JSON 裡，answer 欄位自己又是一段完整 JSON（自我包裝），post-process 沒拆解。修法：answer 後處理新增 `_unwrap_self_referential_json` 保守 helper — 只在 answer 開頭是 `{` 且能 parse 成功且含 `"answer"` key 時取裡層字串，否則完全 noop（不會誤改純文本）。新增 3 個 unit test，套用在「JSON parse 成功」與「malformed JSON salvage」兩條 path。Prod smoke：對 EP140 高雄美食那題打對話，answer 是純文字「EP140 高雄美食第二彈的來賓包括樂團大佬楊大正以及張凱婷」沒任何 wrapper。',
      en: 'Chat mode occasionally returned weird-looking strings like `{"answer":"the real answer goes here"}`, which looked like an LLM failure to users and confused the judge during eval (R2.1 RCA pinned this to thisno-core-com-004). Root cause: the LLM occasionally double-wraps the `answer` field — the outer JSON parses cleanly but the inner `answer` value is itself another JSON string. Fix: conservative `_unwrap_self_referential_json` helper in answer post-process — only triggers when the answer string starts with `{` AND parses as a dict AND contains an `"answer"` key, otherwise pure no-op (won\'t touch plain prose). 3 new unit tests cover both the normal JSON-parse path and the malformed-JSON salvage path. Prod smoke: asking "Who were the guests on EP140 Kaohsiung Food round 2" returns clean prose "EP140 高雄美食第二彈的來賓包括樂團大佬楊大正以及張凱婷" with no wrapper.',
    },
    summaryBullets: {
      zh: [
        '對話模式 answer 加 `_unwrap_self_referential_json` 保守 helper：偵測 `{"answer":"..."}` 自我包裝結構後取出裡層字串；非此 shape 完全 noop',
        '套用在「JSON parse 成功」與「malformed JSON salvage」兩條 path — 不論 LLM 回哪種包裝形式都會被攔下',
        '3 個 unit test：純文本不變動 / JSON wrapped 拆解 / JSON 但沒 answer key 不動',
        'Prod smoke：EP140 高雄美食那題對話回答是純文字，無 `{"answer":...}` wrapper',
      ],
      en: [
        'Chat answer post-process gains `_unwrap_self_referential_json` conservative helper — detects `{"answer":"..."}` self-wrapped shape and extracts the inner string; non-matching answers pass through untouched',
        'Applied at both the JSON-parse-success path and malformed-JSON salvage path so no matter which wrapper form the LLM returns, it gets caught',
        '3 unit tests cover plain prose (no-op), JSON wrapped (unwrap), and JSON without answer key (no-op)',
        'Prod smoke: EP140 Kaohsiung Food query returns plain prose answer with no wrapper visible',
      ],
    },
  },
  {
    date: '2026-05-17', slug: 'enumeration-topic-finder-include-title', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '標題寫了主題、內文沒寫的集數，現在也會列進「相關集數」清單',
      en: 'Episodes Whose Topic Lives Only in the Title Now Surface in Enumeration Results',
    },
    summary: {
      zh: '今天先做了一輪 golden set audit — 拿「節目裡有哪些集是歌單？」這題的 expected 25 集對照 prod chat 實際回的 23 集，發現兩件事：(1) 有 2 集（EP43 金屬樂、EP12 KPOP）description 明明列了完整歌單但題目沒標進 expected → 補進去變成 27 集；(2) 真正的 retrieval bug：有 6 集（EP19 動漫歌單、EP84 嘻哈歌單、EP87 紀念歌單、EP89 搖滾歌單、EP96 夏日節拍歌單、EP108 雷鬼歌單）的「歌單」二字只出現在標題、description 完全沒寫，結果完全從相關集數清單中漏掉。根因：負責找「主題符合的集數」的程式只看每集 description 內文，從來沒看標題。修法：那段查詢加上「標題符合 OR 內文符合」就好，不引入新欄位、不做 backfill、不換 schema。考慮過用 ai_summary（LLM 寫的內容摘要）救援但只能救 6 漏撈集中的 1 集，且要新增欄位 + 回填 520 集 + 同步維護，成本高 10 倍效益 1/6，YAGNI；也驗證過要不要抓 RSS 的 itunes:keywords 但三個節目（這又沒有很屌、曼報、壹加壹電台）的 episode 層級全部空 — 台灣 podcast 託管平台常態，沒人手填這個 tag。Prod 結果：q25 歌單題 episode_set_recall 從 0.78 拉到 1.0（27/27 全命中）、aggregate enumeration 從 0.88 → 1.0、chunk_id 題 Recall@5 byte-identical 0.86 零 regression。抽樣其他 topic 題（動漫 / 雷鬼 / 高雄美食）：雷鬼題 EP108 雷鬼歌單也順帶救回來，其他題 0 false positive。',
      en: 'Started today with a golden set audit — compared the expected 25 episodes for q25 "Which episodes are playlist episodes?" against the 23 episodes chat actually returns in prod, and found two things: (1) 2 episodes (EP43 metal, EP12 KPOP) clearly list a full playlist in their description but were never tagged as expected → bumped expected to 27; (2) the real retrieval bug: 6 episodes (EP19 anime, EP84 hiphop, EP87 memorial, EP89 rock, EP96 summer beats, EP108 reggae) have 「歌單」only in their TITLE — their descriptions never use the word — so they were silently missing from the Related Episodes list entirely. Root cause: the function that finds "episodes matching a topic" only ever consulted episode descriptions, never the title. Fix: add `OR title matches` to the query. No new column, no backfill, no schema change. Considered using `ai_summary` (LLM-generated content summary) as a fallback but it would only rescue 1 of the 6 missing episodes while needing a new column + 520-episode backfill + sync maintenance — 10x the cost for 1/6 the benefit, YAGNI. Also verified whether to ingest RSS `itunes:keywords` but all three shows (這又沒有很屌, 曼報, 壹加壹電台) ship empty at the episode level — Taiwan podcast platform norm, no one fills those tags. Prod result: q25 playlist episode_set_recall 0.78 → 1.0 (27/27 hit), aggregate enumeration 0.88 → 1.0, chunk_id Recall@5 byte-identical 0.86 zero regression. Sampled other topic queries (anime / reggae / Kaohsiung food): reggae also rescues EP108 reggae-playlist incidentally, other queries zero false positives.',
    },
    summaryBullets: {
      zh: [
        '主題型列舉問題現在會同時看每集標題與描述：「歌單那幾集」從 23 集 → 29 集，6 集標題寫「歌單」但描述沒寫的集數（EP19/EP84/EP87/EP89/EP96/EP108）不再被漏掉',
        'Golden set q25 順手 audit：補 EP43 金屬樂 + EP12 KPOP 進 expected（描述列了完整歌單但題目沒標），expected 25 → 27 集',
        'Prod 結果：q25 episode_set_recall 0.78 → 1.0、aggregate enumeration 0.88 → 1.0、chunk_id Recall@5 byte-identical 0.86 零 regression',
        '評估排除過的選項：用 ai_summary（只能救 1/6 + 成本高 10 倍 = YAGNI）、抓 RSS itunes:keywords（三個 show 上游全空，這條路不存在）— 都記入 design.md 的 Alternatives Rejected',
        '單一 SQL 改動、不新增欄位、不做 backfill；EXISTS-OR 形式天然 distinct by episode_id，比 UNION ALL 少一層 dedupe',
      ],
      en: [
        'Topic-driven enumeration now consults BOTH per-episode title and description: "playlist" goes from 23 → 29 episodes, recovering all 6 title-only episodes (EP19/EP84/EP87/EP89/EP96/EP108) that were silently dropped before',
        'Golden set q25 audit: added EP43 (metal) + EP12 (KPOP) to expected — their descriptions list full playlists but the dataset missed them. Expected 25 → 27',
        'Prod result: q25 episode_set_recall 0.78 → 1.0, aggregate enumeration 0.88 → 1.0, chunk_id Recall@5 byte-identical 0.86 zero regression',
        'Rejected alternatives (captured in design.md): using ai_summary (rescues only 1/6 at 10x cost = YAGNI), ingesting RSS itunes:keywords (all three shows ship empty at episode level — this avenue does not exist upstream)',
        'Single SQL change, no new column, no backfill; EXISTS-OR form is naturally distinct by episode_id, one fewer dedup layer than UNION ALL',
      ],
    },
  },
  {
    date: '2026-05-17', slug: 'enumeration-rule-pattern-broaden', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '「高雄美食的集數有哪些」這種反序問法現在也能列出集數了 — 順便挖出更深的 CJK 切詞 bug',
      en: 'Reversed-Structure Questions Like "Which Episodes Cover Kaohsiung Food" Now Trigger Enumeration — and Surfaced a Deeper CJK Tokenization Bug',
    },
    summary: {
      zh: '昨天 ship r3-3-chat-enum-grounding 後跑 eval baseline 發現 q26「節目裡有講過高雄美食的集數有哪些？」episode_set_recall 持平 0.333 沒升，q25「節目裡有哪些集是歌單？」卻升到 0.76。兩題都是列舉題、結構幾乎一樣，只差問句字序。挖下去發現兩層問題：(1) rule pattern 只認得「哪/那 + 集」正序結構（如「哪幾集」「有哪些集」），不認得「集數有哪些」「集有哪些」這類反序問法 — 把 regex 擴張一條 `集數?有[哪那]些` 解決；不擴張到無「集」字的「有哪些」「哪些是」（譬如「主持人有哪些？」會誤命中）。(2) 修完 regex 後 q26 確實觸發 enumeration 路徑，但 SQL 還是回 0 集 — 因為 LLM 抽出的多字 phrase「高雄美食」整段塞進 Postgres `to_tsquery(simple, ...)`，simple analyzer 不切 CJK，把「高雄美食」當一個 lexeme 對不上每集 description 存的 jieba 切過的「高雄」「美食」單字 token。修法：`find_episodes_by_topic` 在組 tsquery 前對每個 topic term 跑 jieba 切再 OR-join。Prod 結果：q26 從 0.333 → 1.0（chat 回 16 集，expected 6 集全命中）、q25 維持 0.76 zero regression、aggregate enumeration 從 0.5467 → 0.88 (+33pp)、chunk_id 題 byte-identical。',
      en: 'After yesterday\'s r3-3-chat-enum-grounding shipped we ran the eval baseline and noticed q26 "Which episodes cover Kaohsiung food?" stayed flat at 0.333 while q25 "Which episodes are playlist episodes?" jumped to 0.76. Both are enumeration items with nearly identical structure, differing only in question word order. Two layers of issues surfaced: (1) the rule pattern only matched 哪/那 + 集 in forward order ("哪幾集" / "有哪些集"), missing reversed structures like "集數有哪些" / "集有哪些" — fixed by widening the regex with `集數?有[哪那]些` (carefully NOT extending to bare "有哪些" without 集, which would falsely match "主持人有哪些?"). (2) Once regex fixed and the path triggered, SQL still returned 0 episodes for q26 — the LLM-extracted multi-char phrase "高雄美食" was passed whole to Postgres `to_tsquery(simple, ...)`, and the simple analyzer does NOT segment CJK, so "高雄美食" became a single lexeme that never matched the jieba-tokenised descriptions which store "高雄" and "美食" as separate words. Fix: `find_episodes_by_topic` now jieba-tokenises each topic term BEFORE OR-joining for the tsquery. Prod result: q26 went 0.333 → 1.0 (chat returned 16 episodes covering all 6 expected ones), q25 held at 0.76 zero regression, aggregate enumeration 0.5467 → 0.88 (+33pp), chunk_id items byte-identical.',
    },
    summaryBullets: {
      zh: [
        'Rule pattern 加一條 `集數?有[哪那]些` 涵蓋「集數有哪些」「集有哪些」這類反序問法；不擴張到無「集」字的句型避免「主持人有哪些」誤命中',
        '`find_episodes_by_topic` SQL 組裝前對每個 topic term 先用 jieba 切（譬如「高雄美食」→「高雄」+「美食」），避免 Postgres simple analyzer 不切 CJK 導致整段 phrase 對不上每集描述存的單字 token',
        '某 term jieba 切後全是 stopword 則 fallback 留原 term，不丟訊號',
        'Prod eval：q26 0.333 → 1.0、aggregate enumeration 0.5467 → 0.88、chunk_id Recall@5 0.86 byte-identical',
        'Spec 加 ADDED「Topic-driven enumeration finder pre-tokenises LLM phrases with jieba」+ rule pattern MODIFIED 補三個 scenarios',
      ],
      en: [
        'Rule pattern gains a `集數?有[哪那]些` arm covering reversed structures like "集數有哪些" / "集有哪些"; deliberately NOT extending to bare "有哪些" without 集 (avoids false positives like "主持人有哪些?")',
        '`find_episodes_by_topic` now jieba-tokenises each topic term BEFORE OR-joining into the tsquery (e.g. "高雄美食" → "高雄" + "美食"), closing the impedance mismatch between Postgres simple analyzer (no CJK segmentation) and the jieba-tokenised description corpus',
        'When jieba reduces a term to all-stopwords, the raw term is retained as fallback so the LLM signal is not silently dropped',
        'Prod eval: q26 0.333 → 1.0, aggregate enumeration 0.5467 → 0.88, chunk_id Recall@5 0.86 byte-identical',
        'Spec adds Topic-driven enumeration finder pre-tokenises LLM phrases with jieba + MODIFIED rule pattern with 3 new scenarios',
      ],
    },
  },
  {
    date: '2026-05-16', slug: 'eval-runner-chat-enum-scoring', milestone: 'v1.7', tag: 'enhancement',
    title: {
      zh: '量測補洞：「歌單那幾集」分數從 0.04 跳到 0.76 — 不是系統變好，是過去我們算錯了',
      en: 'Measurement Fix: "Playlist" Score Jumped from 0.04 to 0.76 — Not Because the System Got Better, but Because We Were Mis-Scoring',
    },
    summary: {
      zh: '今天稍早 ship r3-3-chat-enum-grounding（讓 chat 回應正確列出相關集數）後我們跑 eval baseline 抓到一個尷尬數字：q25「節目裡有哪些集是歌單？」episode_set_recall = 0.04（命中 1/25 集），看起來像沒進步。但實際打 chat endpoint 拿到 23 集相關集數列表中真的有 19 集在 expected 集合內 — 0.76 的命中率。差距 19 倍。原因：eval runner 從一開始就只看 search endpoint 回的 top-5 chunks 推算 episode_set_recall，從來不打 chat endpoint，所以 chat 路徑新加的 enumeration_episodes 欄位完全沒進計分。這次補洞：runner 對 enumeration 題型同時打 search + chat 兩條路徑，episode_id 聯集後計算 recall。所有非 enumeration 題型保持只打 search（cost 不變）。每題 JSON 報表額外帶 enumeration_episodes_count + episode_set_recall_chat_only 兩個 diagnostic 欄位，方便追蹤 chat / search 兩條路徑的差異。Prod 重跑結果：q25 從 0.04 → 0.76（+19 倍）、aggregate enumeration recall 從 0.1867 → 0.5467（+3 倍）、chunk_id 題目 Recall@5 byte-identical 0.86（零 regression）。**對使用者體驗沒有任何 behavior 改動** — 這純粹是量測工具補完整，讓接下來任何 retrieval / enumeration 改動的 lift 能被正確量化，避免再瞎子飛。',
      en: 'Earlier today after shipping r3-3-chat-enum-grounding (which lets chat responses list relevant episodes correctly), we ran the eval baseline and saw an awkward number: q25 "Which episodes are playlist episodes?" scored episode_set_recall = 0.04 (1 of 25 matched), looking like no improvement. But directly hitting the chat endpoint, the enumeration_episodes list contained 23 episodes, of which 19 were in the expected set — 0.76 hit rate. 19x gap. Root cause: the eval runner only ever scored enumeration items against the search endpoint top-5 chunks and never called the chat endpoint, so the new enumeration_episodes field shipped by R3.3 + r3-3-chat-enum-grounding was completely invisible to scoring. This release closes the gap: the runner now calls BOTH search and chat for enumeration items, unions the episode_ids, and computes recall against the union. Non-enumeration items continue to only hit search (cost unchanged). Per-item JSON gains two diagnostic fields (enumeration_episodes_count + episode_set_recall_chat_only) to make search-vs-chat divergence trackable. Prod re-run: q25 went 0.04 → 0.76 (+19x), aggregate enumeration recall 0.1867 → 0.5467 (+3x), chunk_id Recall@5 stays byte-identical at 0.86 (zero regression). **No user-facing behavior change** — this is pure measurement infrastructure, so any future retrieval / enumeration improvement can be properly quantified instead of flying blind.',
    },
    summaryBullets: {
      zh: [
        'Eval runner 對 enumeration 題型現在同時打 search + chat 兩條路徑，episode_id 聯集計算 recall',
        '非 enumeration 題目（chunk_id / open_set_lenient）保持只打 search，cost + 行為與之前 byte-identical',
        'Prod 重跑：q25 歌單 0.04 → 0.76 (+19x)、aggregate enumeration 0.1867 → 0.5467 (+3x)、chunk_id Recall@5 0.86 零 regression',
        'JSON 報表每題多 enumeration_episodes_count + episode_set_recall_chat_only 兩欄位，讓 chat / search 兩條路徑差異可追蹤',
        '使用者體驗零變化；純量測工具補完整，讓接下來改動的 lift 能被正確算出來',
      ],
      en: [
        'Eval runner now calls BOTH search + chat for enumeration items and unions the episode_ids for recall scoring',
        'Non-enumeration items (chunk_id / open_set_lenient) keep search-only path; cost + behavior byte-identical to before',
        'Prod re-run: q25 playlist 0.04 → 0.76 (+19x), aggregate enumeration 0.1867 → 0.5467 (+3x), chunk_id Recall@5 0.86 zero regression',
        'Per-item JSON gains enumeration_episodes_count + episode_set_recall_chat_only diagnostic fields so chat-vs-search divergence is trackable',
        'No user-facing behavior change; pure measurement infra so future improvements can be quantified',
      ],
    },
  },
  {
    date: '2026-05-16', slug: 'r3-3-chat-enum-grounding', milestone: 'v1.7', tag: 'enhancement',
    title: {
      zh: 'Chat 答案文字現在會對齊「相關集數」卡片數字 + 主題型問題也能列出集數',
      en: 'Chat answer text now aligns with the Related Episodes card count + topic-only queries also surface the list',
    },
    summary: {
      zh: 'R3.3 metadata-filter 上線後我們抓到三個交織的痛點：(1) 問「楊大正是哪幾集的來賓？」chat 文字回「1 集」但下方卡片其實顯示 2 集 — 因為回答模型只看到搜尋撿出的 8 段對話片段，沒看到完整的「相關集數」清單，硬從片段子集推論集數；(2) 單獨輸入「歌單」沒有列出相關集數 — 因為主題詞欄位早就由 LLM 抽出來了，但決定「要不要列集數」的程式沒用它；(3) 問「歌單哪幾集」結果列出全節目 164 集 — 因為原本 spec 寫要做的「主題詞篩集數」我那時偷懶沒寫。這次三件一起補：(a) 回答模型的 prompt 現在會在前面預先注入「共 N 集」的結構化清單，模型答案數字直接對齊卡片；(b) 主題詞欄位也能觸發列舉，不再閒置；(c) 主題詞會去比對每集簡介內容，「歌單那幾集」現在精準回 23 集（節目裡真的做歌單的集數），不是傻列 164 集。前端配合做了階段式顯示：相關集數預設只顯示 10 集，「再顯示 10 集」按鈕點一次加 10，全部顯示完才停 — 手機看 100+ 集的列表不會被灌爆。後端架構也順便重構成 tool-like 三個獨立函式（依來賓 / 主題 / 日期分別找），為未來 agentic RAG 升級留好接口。Prod 實測：「楊大正」回 2 集對齊、「歌單那幾集」回 23 集精準、「林志炫」（不存在的來賓）誠實回 0 集 + 文字明說沒找到。',
      en: 'After R3.3 metadata-filter shipped we caught three interlocked pain points: (1) "Which episodes featured 楊大正?" — chat text said "1 episode" but the card list below correctly showed 2, because the answer model only ever saw the top-8 retrieval chunks and guessed the count from that subset; (2) typing just "歌單" produced no enumeration list because the topic field was already extracted by the LLM but the "should we list episodes?" function ignored it; (3) "歌單哪幾集" returned all 164 episodes of the show because the topic-keyword SQL filter the spec called for was never written. This release fixes all three together: (a) the answer prompt now prepends a structured grounding block listing the matched episodes BEFORE the chunk citations, so the model grounds its prose count on the enumeration list; (b) topics now trigger the enumeration path; (c) topic terms run against per-episode descriptions, so "歌單哪幾集" returns 23 real playlist episodes rather than the entire show. Frontend gained stepwise display: the enumeration card list defaults to 10 visible, with a "Show 10 more" button incrementing by 10 — mobile no longer gets dumped with 100+ cards at once. Backend refactored into three tool-like finder functions (by guest / by topic / by date) preparing the seam for future agentic-RAG upgrades. Prod verified: "楊大正" returns 2 (aligned), "歌單那幾集" returns 23 precisely, "林志炫" (non-existent guest) honestly returns 0 + answer text says no match.',
    },
    summaryBullets: {
      zh: [
        'Chat 答案文字數字現在與相關集數卡片一致：回答模型 prompt 預先注入「共 N 集」結構化清單，不再從片段子集亂推',
        '主題型問題（譬如「歌單」「高雄美食」）也能觸發相關集數列舉 — 之前 LLM 抽出來的 topic 欄位被閒置，現在接上 SQL',
        '「歌單哪幾集」現在精準回 23 集（節目裡真的做歌單的集數），不是傻列全節目 164 集',
        '相關集數階段式顯示：預設 10 集 + 「再顯示 10 集」按鈕，手機不會被 100+ 集列表灌爆',
        '來賓+主題複合題（譬如「馬世芳那幾集講過烤肉」）走 AND；交集 0 集時自動 fallback 給來賓的全部集數並標警告',
        '後端拆成 tool-like 三函式（by guest / topic / date），為未來 agentic RAG 留接口；74 個單元測試全綠',
      ],
      en: [
        'Chat answer count now matches the Related Episodes card count: answer prompt prepends a structured grounding block listing "N episodes" before the chunk citations, no more guessing from a subset',
        'Topic-only queries (e.g. "歌單", "高雄美食") trigger the enumeration list too — the LLM-extracted topics field was previously idle, now wired to SQL',
        '"歌單哪幾集" returns 23 real playlist episodes precisely (was: every episode of the show, 164)',
        'Stepwise display: card list defaults to 10, "Show 10 more" button increments by 10 — mobile no longer gets dumped with a 100+ card list',
        'Guest + topic combination (e.g. "馬世芳那幾集講過烤肉") AND-intersects; on empty intersection auto-falls back to guest-only with a warning header',
        'Backend refactored into three tool-like finder functions (by guest / topic / date) — preps the seam for future agentic RAG; 74 unit tests passing',
      ],
    },
  },
  {
    date: '2026-05-16', slug: 'chat-input-ime-composition-fix', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '注音輸入法 Enter 選字不再誤送 — 對話框與語意搜尋框 IME safety',
      en: 'Bopomofo / CJK IME: Enter no Longer Hijacks Candidate-Confirm in Chat + Semantic-Search Inputs',
    },
    summary: {
      zh: '注音、倉頡、拼音這類 CJK 輸入法的選字流程靠按 Enter 確認候選字。先前 QueryPage 的對話框和語意搜尋框 onKeyDown 抓到 Enter 就直接 handleSend/handleSearch，沒有區分「Enter 選字」與「Enter 送出」兩種語意 — 結果使用者打到一半（譬如打「歌單那幾集」打到「歌單」就按 Enter 選「單」字）→ 整句被半途送出，要重打。對台灣使用者根本天天卡。這次把 IME composition guard（檢查 `e.isComposing` 與 legacy `keyCode === 229`，後者覆蓋 Safari / iOS）集中到共用的 `<Input>` 元件，新增 `onSubmit` prop 內建這層保護。對話框與語意搜尋框遷移到新介面；未來新增任何輸入框只要用 `onSubmit={handler}` 就自動享有 IME 安全。Prod 使用者實測：注音逐字選字 Enter 都不送出、純英文 Enter 立刻送、語意搜尋 Enter 也正常觸發 — 全綠。',
      en: 'CJK input methods (Bopomofo, Cangjie, Pinyin etc.) use Enter to confirm the highlighted candidate in their popup. The chat + semantic-search inputs on QueryPage had a naive `onKeyDown={e.key === "Enter" && submit()}` handler with no composition guard — pressing Enter to confirm a Bopomofo character mid-typing would submit a half-finished query and force the user to start over. Every-day blocker for the project\'s near-100% CJK userbase. This release centralizes the IME composition guard (`e.isComposing` + legacy `keyCode === 229` for Safari/iOS) into the shared `<Input>` component, exposed via a new `onSubmit` prop. Chat + semantic-search inputs migrated to the new interface; any future input that uses `<Input onSubmit={…}>` now gets IME safety for free. Real-user IME verification on prod: Bopomofo candidate-confirm Enter does NOT submit, plain English Enter DOES submit, semantic-search Enter triggers search — all clear.',
    },
    summaryBullets: {
      zh: [
        '對話框 + 語意搜尋框 Enter 改走 IME composition guard：`e.isComposing` 為真或 `keyCode === 229`（Safari/iOS legacy 路徑）時跳過送出',
        '保護集中到共用 `<Input>` 元件新增 `onSubmit` prop — 未來任何 input 用這個介面自動享有 IME 安全',
        '修補 follow-up：QueryPage 兩個 handler signature 對齊（handleSearch 的 overrideQuestion arg 被 KeyboardEvent 污染導致 `.trim()` 拋錯靜默失敗，包一層 `() => handler()` drop event arg）',
        '使用者實測：注音逐字選字 Enter 不誤送 ✅、英文純 Enter 送出 ✅、語意搜尋 Enter 觸發 ✅',
      ],
      en: [
        'Chat + semantic-search Enter now goes through IME composition guard: when `e.isComposing` is true or `keyCode === 229` (Safari/iOS legacy path), submission is skipped',
        'Guard centralized in shared `<Input>` via new `onSubmit` prop — any future input that uses this interface gets IME safety for free',
        'Follow-up fix: QueryPage handlers wrapped as `() => handler()` so the KeyboardEvent never leaks into `handleSearch(overrideQuestion?: string)`, which was silently throwing on `event.trim()` inside async',
        'Real-user verification: Bopomofo candidate-confirm Enter does NOT misfire submit ✅, plain English Enter DOES submit ✅, semantic search Enter triggers ✅',
      ],
    },
  },
  {
    date: '2026-05-16', slug: 'r3-3-metadata-filter', milestone: 'v1.7', tag: 'enhancement',
    title: {
      zh: '問「馬世芳上過哪幾集？」可以直接看到清單了 — 加上來賓清單、發佈日期、跨集列舉',
      en: 'Ask "Which Episodes Featured 馬世芳?" and Get the Actual List — Guest Names, Publish Dates, Cross-Episode Enumeration',
    },
    summary: {
      zh: '之前查詢只能拉「跟你的問題相關的逐字稿片段」回答，沒辦法直接告訴你「這個來賓在哪幾集出現過」或「2024 年那集是哪集」。這次把節目層級的 metadata 補進 RAG：(1) 從 RSS 標題自動抽 guests（譬如「Ft. 馬世芳」→ 寫進 episodes.guests JSONB），約 93/164 集有 guests；(2) 後台新增「來賓管理」分頁，標題沒寫 Ft. 但實際有來賓的集數可以手動補；(3) chat 查詢時 LLM 會抽出問題裡的 guest 名稱 + 日期區間，retrieval SQL 加上 hard filter 縮小範圍；(4) 對話結果新增「相關集數」section — 條件是問題裡包含 guest 名 / 日期 / 「哪幾集」這類 rule pattern 任一即觸發，每集卡片含 title + 發佈日期 + guests chips + AI 摘要 + 「跳到這集」按鈕。Backend retrieval 同時做了三池 RRF 重構（transcript / description / 標題各自獨立 lexical 池，權重可線上調整不需要重 index）。Prod 驗證：「馬世芳上過哪幾集」回 1 集 EP143（這 show 只有一集 ft. 馬世芳）；「楊大正是哪幾集的來賓」回 2 集。**已知限制**：chat 答案文字目前看不到 enumeration list（會說「1 集」即使下面列了 2 集），「歌單」topic 單獨輸入不會觸發列舉 — 這兩件下個 change `chat-enum-grounding` 處理。',
      en: 'Until now, chat queries could only fetch transcript snippets relevant to your question — there was no way to directly answer "which episodes featured guest X?" or "the episode from 2024 — which one?". This release adds show-level metadata into RAG: (1) extract guests from RSS titles automatically (e.g. "Ft. 馬世芳" → `episodes.guests` JSONB), roughly 93/164 episodes carry guests; (2) new admin "Guests" tab for episodes whose titles do not use Ft. but have real guests — can be filled manually; (3) chat queries run an LLM entity extractor on the question to pull guest names + date ranges, applied as SQL hard filters; (4) chat response gains a "Related Episodes" section — triggered when the question carries a guest name / date / rule-pattern phrases like 「哪幾集」 — each card shows title + publish date + guest chips + AI summary + a "Jump to this episode" button. Backend retrieval also gained a three-pool RRF refactor (transcript / description / episode-title lexical pools each ranked independently with tunable weights, no re-indexing required). Prod verified: "Which episodes featured 馬世芳?" returns 1 (EP143, the only ft.-馬世芳 episode); "Which episodes did 楊大正 guest on?" returns 2. **Known limits**: the chat answer text does not yet see the enumeration list (it may say "1 episode" even when the card list below shows 2), and topic-only queries like "歌單" do not trigger the list — both will be handled by the next change `chat-enum-grounding`.',
    },
    summaryBullets: {
      zh: [
        'RSS 自動抽 guests 寫進 `episodes.guests` JSONB（約 93/164 集），後台新增「來賓管理」tab 可手動補',
        'Chat query LLM 抽 guest / date entity，retrieval SQL 加 hard filter；同時加 BM25 三池 RRF（transcript / description / 標題）權重可線上 tune',
        '對話結果新增「相關集數」section：guest 名 / 日期 / 「哪幾集」rule pattern 任一觸發，每集卡片含 title + 發佈日期 + guests chip + 跳到這集 button',
        '相容雙寫：「哪」「那」都觸發（注音輸入常打錯）；LLM 偶發回 malformed JSON 也不會把 JSON 殘骸顯示給使用者',
        '已知限制：chat 答案文字不知道 enumeration list 內容（會說「1 集」但下面列 2 集）+ topic-only 不觸發列舉，下個 change `chat-enum-grounding` 解決',
      ],
      en: [
        'RSS auto-extracts guests into `episodes.guests` JSONB (~93/164 episodes); new admin "Guests" tab lets operators backfill the rest by hand',
        'Chat queries run an LLM extractor pulling guest / date entities → SQL hard filter; backend also gains 3-pool BM25 RRF (transcript / description / episode title) with tunable weights, no re-index needed',
        'Chat response gains a "Related Episodes" section: triggered by guest name / date / phrases like 「哪幾集」 — each card has title + publish date + guest chips + a "Jump to this episode" button',
        'Compatibility fixes: both 哪 and 那 trigger the enumeration path (common Bopomofo IME typo); malformed-JSON answers from the model no longer leak the JSON wrapping into the chat bubble',
        'Known limits: the chat answer text does not yet see the enumeration list (may say "1 episode" while the card list below shows 2), and topic-only queries do not trigger the list — addressed by the next change `chat-enum-grounding`',
      ],
    },
  },
  {
    date: '2026-05-14', slug: 'eval-runner-enumeration-scope', milestone: 'v1.7', tag: 'enhancement',
    title: {
      zh: '量得到「節目裡到底有幾集是歌單」這種題了 — 為列舉型查詢開新的計分路徑',
      en: 'Now We Can Score "List-All-Episodes" Questions — A New Scoring Lane for Enumeration Queries',
    },
    summary: {
      zh: '之前 RAG 測試集問的都是「某一集講了什麼」這類定點題：把預期的逐字稿片段（chunk）列出來，搜尋有沒有命中那幾個 chunk 就算分。但我們其實也想知道使用者問「節目裡有哪些集是歌單？」、「有講過高雄美食的集數有哪些？」這種「**請列出所有相關集數**」的題目時，retrieval 拉出來的結果到底涵蓋了多少正確集數。問題是 eval runner 沒有對應的計分模式 — 跑到這種題會被誤判為「沒有 ground truth → 沉默排除」，整題消失在報表上，等於白跑。這次把「該怎麼算分」變成測試集的第一公民欄位 `eval_mode`，每題顯式聲明三種模式之一：`chunk_id`（定點題，舊行為不變）/ `open_set_lenient`（跨集弧線題，命中任一 anchor 即算）/ `enumeration`（列舉題，算「retrieval 涵蓋了預期集數集合的幾趴」）。Runner 看到 `enumeration` 題會走新計分路徑：`episode_set_recall = |retrieved ∩ expected| / |expected|`，不再跟一般 Recall@5 混在一起算平均，報表也拆成兩段獨立呈現。順手做了三件事：(1) 既有 30 題回填 `eval_mode` 欄位（合併 `narrowed_two_anchor` 進 `open_set_lenient`，反正行為一樣）；(2) 加 8 個 schema validator 單元測試 + 7 個 dispatch 單元測試守門；(3) 對 prod 跑完 n=30 baseline，q26（高雄美食列舉題）拿到 0.333（命中 2/6 集，top_k=5 上限是 0.83），q25（歌單列舉題）拿到 0.08（命中 2/25 集，top_k=5 上限只有 0.20 — 這個結構性天花板會在下一個 change `eval-runner-dynamic-top-k` 解掉）。**對使用者體驗沒有任何 behavior 改動**；這純粹是為了讓接下來的 R3.3 metadata-filter 上線後能驗證「列舉題召回有沒有真的變好」做的測量工程。',
      en: 'Until now, our RAG test set only handled "what did episode X say about Y" — point queries: list the expected transcript chunks, count how many show up in retrieval. But users also ask "which episodes are music-playlist episodes?" or "which episodes covered Kaohsiung food?" — *enumerate-all-relevant-episodes* queries. The eval runner had no scoring lane for these: with empty `ground_truth_chunk_ids`, items silently dropped out of the Recall mean entirely. This release makes "how to score" a first-class field, `eval_mode`, declared per-item with one of three modes: `chunk_id` (point queries, legacy behavior unchanged) / `open_set_lenient` (cross-episode arc questions, any-anchor-hit counts as 1.0) / `enumeration` (list queries, scored as `|retrieved ∩ expected| / |expected|` over episode sets). The runner dispatches on `eval_mode` per item; enumeration items aggregate into their own metric group instead of polluting the chunk-based Recall mean, and the markdown report now renders two separate rows. Bundled three things alongside: (1) backfilled `eval_mode` on all 30 existing items (folded the prior `narrowed_two_anchor` value into `open_set_lenient` — same behavior); (2) 8 schema-validator unit tests + 7 dispatch unit tests as guardrails; (3) ran a fresh n=30 prod baseline — q26 (Kaohsiung food enumeration) scored 0.333 (2 of 6 episodes hit, top_k=5 ceiling is 0.83), q25 (playlist enumeration) scored 0.08 (2 of 25, top_k=5 ceiling only 0.20 — this structural ceiling will be lifted by a follow-on change `eval-runner-dynamic-top-k`). **No user-facing behavior change**; this is pure measurement infrastructure so the upcoming R3.3 metadata-filter has a way to prove "enumeration recall actually improved" once it ships.',
    },
    summaryBullets: {
      zh: [
        '測試集每題現在要明寫 `eval_mode`，runner 看 mode 分三條計分路徑：定點題 / 跨集弧線題 / 列舉題各自獨立 — 不再彼此污染平均分',
        '列舉題拿到專屬指標 `episode_set_recall`：q26（高雄美食）= 0.333 命中 2/6 集；q25（歌單）= 0.08 命中 2/25 集（受 top_k=5 結構性壓制，下個 change 解掉）',
        '報表表格從「一行 Overall Recall」變兩行：chunk-based n=18 / enumeration n=2 — 不混算，看趨勢更乾淨',
        '使用者體驗零變化；這是為了下一階段「R3.3 metadata-filter 跨集召回」能驗證做的測量基礎工程',
      ],
      en: [
        'Every test-set item now declares `eval_mode` explicitly; runner dispatches into three lanes (chunk_id / open_set_lenient / enumeration) so the metrics no longer cross-contaminate one another',
        'Enumeration items get their own metric: q26 (Kaohsiung food) hit 2/6 episodes (0.333); q25 (playlists) hit 2/25 (0.08), capped by top_k=5 structurally — to be lifted by a follow-on change',
        'Markdown report rows split from one "Overall Recall" line into two: chunk-based n=18 / enumeration n=2 — cleaner trend signal',
        'Zero user-facing behavior change; this is measurement infrastructure so the next-up R3.3 metadata-filter has a way to prove cross-episode recall actually improves once shipped',
      ],
    },
  },
  {
    date: '2026-05-13', slug: 'r3-5-disable-routing', milestone: 'v1.7', tag: 'fix',
    title: {
      zh: '搜尋常找不到正確答案？關掉一層擋路的路由邏輯，準度直接 7 倍',
      en: 'Search Could Not Find the Right Episode — One Routing Layer Was the Culprit, Now Disabled',
    },
    summary: {
      zh: '到 v1.6 為止，搜尋有個藏很深的問題：問「節目名「這又沒有很屌」是怎麼來的？」這種帶節目名的問題時，系統不是找講由來的 EP1，而是把「description 裡有提到《這又沒有很屌》」的後面集數推到前面（那些只是開頭歡迎詞 “歡迎收聽 XX EP128…”，根本沒講由來）。背後是 5/11 加進來的 two-layer routing：每筆 query 先用 description embedding 把節目挑出 top-10 候選 episodes，再去這 10 集裡撈片段。但 routing 那層是「純語意 cosine、沒 lexical 信號」，遇到 query 帶專有名詞時被書名字串拉走，正確答案的集數連 top-10 都進不去，後面再強的 retrieval 都救不了。這次把 routing 預設關掉（env flag 早就在那、就是切預設值），同樣 10 題人工測試集的 Recall@5 從 0.0625 升到 0.4375（7 倍）、P95 延遲 2170ms（遠低於 4500ms 容忍上限）。順手做了一次測試集 audit：移出 36 個 LLM 自動生成的爛題（單關鍵字觸發深度問題、anchor 對不上 question），把測試集純化成 10 題人工親寫的 sentinel。LLM 自動產題目這條路不是不能用，但加 staging + 人工二次審核才行——build_golden_set.py 已加守門：要寫主測試集必須 `--target-main` + `--reviewed-by` + `--reviewed-at` 三者齊備，否則只進 `_pending_review.json` staging。同一波 archive 把 r3-4 (text-embedding-3-large) 也一起收尾：embedding 升級保留 in prod，但承認原本宣稱的「fact +95%」幾乎全來自被污染的測試集——真正讓使用者體驗變好的是這次關掉 routing，不是 embedding swap。',
      en: 'Through v1.6, search had a deeply hidden flaw: asking "where does the show name 《這又沒有很屌》come from?" did NOT surface EP1 (which actually tells the origin story); instead, later episodes that merely *mention* the show name in their description ("welcome back to 《這又沒有很屌》 EP128…") ranked higher. Root cause: a two-layer routing pass added 5/11. Every query first runs description-embedding cosine to pick top-10 candidate episodes, then retrieves chunks only from those 10. But the routing layer is pure semantic cosine with NO lexical signal — when a query includes a proper noun (the show title), the cosine match latches onto episodes that literally contain that string, kicking the actual answer episode out of the top 10. No matter how good the downstream retriever is, it cannot recover. This release flips the env-flag default to OFF (the kill-switch was already in code; we just switched the default). On the same 10-item human-curated test set, Recall@5 went from 0.0625 to 0.4375 — a 7x improvement. P95 latency 2170ms, well under the 4500ms ship gate. Also bundled an audit of the test set itself: removed 36 LLM-auto-generated bad items (single-keyword-triggered deep questions, anchors not matching question semantics), keeping only the 10 hand-crafted sentinel items. LLM-auto generation is not banned, but it now must stage through `_pending_review.json` and requires `--target-main` + `--reviewed-by` + `--reviewed-at` to write to the main dataset. Pair-archived r3-4 (text-embedding-3-large upgrade): the embedding model stays in prod, but we are now honest that the originally claimed "fact +95%" was driven almost entirely by the poisoned LLM-auto subset — the real user-facing improvement is this routing fix, not the embedding swap.',
    },
    summaryBullets: {
      zh: [
        '同樣 10 題人工測試集 Recall@5：0.0625 → 0.4375（7 倍），fact / comprehension / cross-episode 都有 gain',
        '帶書名 / 專有名詞的 query 不再被「description 提到該名詞的後面集數」hijack — EP1 由來那集現在 rank 1',
        '測試集移出 36 個 LLM 自動產的爛題（壞題率 ≥ 75%），只留 10 題人工 sentinel；future LLM 產題必須先過 staging 才能進主資料集',
        'P95 延遲 2170ms，遠低於 4500ms ship 容忍上限 — env flag 留著，可隨時切回 routing 做對照',
        '同波 archive r3-4 embedding 升級：保留 v3-large in prod，但承認原本「fact +95%」是測試集污染造成的假象',
      ],
      en: [
        'Same 10-item human-curated set: Recall@5 0.0625 → 0.4375 (7x); fact / comprehension / cross-episode all improved',
        'Queries with proper nouns (show title) no longer hijacked by "later episodes that just mention the title" — EP1 origin story is now rank 1',
        'Removed 36 LLM-auto bad items (verified ≥75% bad-question rate); kept 10 hand-crafted sentinels; future LLM-generated items must stage via `_pending_review.json` with reviewer metadata',
        'P95 latency 2170ms, well below the 4500ms ship gate; env flag preserved so routing can be toggled back on for diagnostics',
        'Pair-archived the r3-4 embedding upgrade (text-embedding-3-large) — model stays in prod, but the previously claimed "fact +95%" is now disclosed as inflated by the poisoned LLM-auto subset, not real user-facing gain',
      ],
    },
  },

  // ─── v1.6 — Eval Tooling (5/11) ───
  {
    date: '2026-05-11', slug: 'eval-runner-flags-patch', milestone: 'v1.6', tag: 'enhancement',
    title: {
      zh: 'Eval 工具可試跑 + 跑到一半當機可接續',
      en: 'Eval Runner: Canary Trial Runs + Crash-Safe Resume',
    },
    summary: {
      zh: '這版改動完全在背景，使用者看不到 — 但對於我們衡量 RAG 答題品質的可信度差很多。eval runner 本來只能整套跑完，跑到一半當機就要重來；而且不會把 LLM 的答案內容存下來，事後只看到分數沒辦法追原因。這次補了 4 個 CLI flag：(1) `--canary 3` 只跑前 3 題給人看 input / output / 評分合不合理才放大；(2) `--persist-answers` 把每題的問題、檢索到的片段、LLM 答案全文落盤，事後可以對著證據追根因；(3) `--checkpoint-every N` 每 N 題寫一次中繼檔，atomic 覆寫；(4) `--resume <path>` 從中繼檔接續跑，會驗證 dataset 是同一份才肯接。為什麼要做？5/10 R2.1 archive 卡關時，Faithfulness 分數從 0.71 掉到 0.50 跑了三輪 eval 都不確定是真退步還是 judge 抖動 — 因為沒存答案文字所以根因都是憑結構推論。這次補完 v2.0 eval skill 強制的 6 phase（preflight / canary / metric-sanity / variance / checkpoint / persistent runner）所需的全部 flag，下一次任何 prompt / retrieval 改動都可以拿證據說話。',
      en: 'This change is entirely behind the scenes — no user-facing surface — but it materially improves how we measure RAG answer quality. Previously the eval runner could only run the full dataset in one go: if it crashed mid-run you started over, and answer text was never persisted so any after-the-fact root-cause analysis was structural guesswork. This release adds four CLI flags: (1) `--canary 3` runs only the first 3 items so you can eyeball inputs / outputs / scores before scaling up; (2) `--persist-answers` writes the question, retrieved chunks, and full LLM answer to disk for every item, enabling evidence-based RCA; (3) `--checkpoint-every N` writes an atomic checkpoint every N items; (4) `--resume <path>` picks up where a crashed run left off, validating the dataset matches before continuing. Why now? During R2.1 archive on 5/10, Faithfulness dropped 0.71 → 0.50 across three eval rounds and we could not tell signal from judge variance because answer text was never persisted. With these flags, the v2.0 eval skill\'s mandatory 6-phase discipline (preflight / canary / metric-sanity / variance / checkpoint / persistent runner) is now fully operational — every future prompt or retrieval change can be defended with evidence.',
    },
    summaryBullets: {
      zh: [
        '`--canary N` 試跑前 N 題 + `--persist-answers` 保存問題 / 檢索內容 / LLM 答案全文',
        '`--checkpoint-every N` atomic 落盤 + `--resume <path>` 從中斷處接續（會驗證 dataset 一致）',
        '11 個 unit test 覆蓋四個 flag + 互斥檢查（`--canary` 與 `--resume` 不能同時用）',
        '純內部工具改動 — 終端使用者完全感覺不到，但 v2.0 eval skill 強制的 6 phase 從這版開始 callable',
      ],
      en: [
        '`--canary N` runs the first N items only; `--persist-answers` dumps question / retrieved chunks / full LLM answer',
        '`--checkpoint-every N` atomic checkpoint + `--resume <path>` picks up after a crash (dataset path is validated)',
        '11 unit tests cover the four flags plus mutex (`--canary` and `--resume` cannot be combined)',
        'Pure internal-tooling change — invisible to end users, but the v2.0 eval skill\'s mandatory 6-phase discipline is now fully callable',
      ],
    },
  },

  // ─── v1.6 — Citation Infrastructure (5/10) ───
  {
    date: '2026-05-10', slug: 'r2-1-citation-infra', milestone: 'v1.6', tag: 'enhancement',
    title: {
      zh: '搜尋結果加上關鍵字高亮、前後文、本集摘要、跳到對應段落',
      en: 'Search Results: Highlights, Context, Summary, and Jump-to-Segment',
    },
    summary: {
      zh: '到 v1.5 為止，搜尋結果只是一塊塊「片段文字 + 集數標題 + 時間戳」，要判斷哪一塊跟你的問題真的相關得自己肉眼掃。從這版開始，每張搜尋結果卡片會做四件事：(1) 把命中的關鍵字用 indigo 加粗加底線標出來（中文分詞跟搜尋同一套，譬如查「方品融」會把這三個字當整體高亮，不會切成「方/品/融」）；(2) 顯示該段前後 2 句的灰色上下文，讓你知道這句話前面在講什麼、後面接什麼；(3) 露出本集 AI 摘要前 60 字當概要，太長有「展開」鈕讓你看完整版；(4) 右下「跳到這段內容」按鈕直接把你帶到逐字稿頁的對應秒數，自動 scroll 並黃色淡入淡出 3 秒高亮——也支援 URL `?show_id=...&episode_id=...&t=秒數` 直接複製連結分享或加書籤，重新整理還會回到原位。如果搜到的是節目主寫的「本集介紹」（沒有特定秒數），按鈕會變成「打開該集」設定正確期待。順手把幾個邊界 bug 也修了：URL 改錯不會跳 alert 直接靜默回首頁、節目簡介卡點下去能正常打開該集（不再卡 t=0.00 沒反應）、答案 LLM 加上拒答模式「真的找不到就說沒有」不再瞎掰。後端送給 LLM 評分時會把 [N] citation 標記 strip 掉避免污染分數。實作中發現了一個更深的問題：retrieval recall 還只有 15%（48 題裡 28 題模型誠實拒答），LLM judge gpt-5-nano 對「正確的拒答」打 0.51（rubric 該給 1.0），這兩個合起來壓低了 Faithfulness 分數，但跟 R2.1 的 UI 改進無關——R3.x retrieval 跟 R1.3 judge 重 calibrate 才是根因解，已寫進 case study 跟路線圖追蹤。',
      en: 'Through v1.5, search results were just blocks of "snippet + episode title + timestamp" — figuring out which block actually answered your question meant reading every line. Starting this release, each result card does four things: (1) Indigo-highlights the matched keyword (bold + underline) using the same Chinese tokenizer as search, so "方品融" stays as one token and gets highlighted as a unit, not three separate characters; (2) Shows the two segments before and after in muted grey so you see the lead-in and continuation; (3) Surfaces the first 60 chars of the episode\'s AI summary as context, with a "Show more" button to expand the full version; (4) A "Jump to transcript" button takes you straight to the right second on the transcript page, auto-scrolling and flashing a yellow highlight for 3 seconds — and the URL contains `?show_id=...&episode_id=...&t=seconds` so you can copy/share the link or bookmark it, and refreshing returns to the same spot. If the result is from the host\'s episode notes (which have no specific timestamp), the button reads "Open episode" to set correct expectations. Bundled bug fixes: editing the URL no longer triggers a popup alert (silent fallback to home), description-source cards now actually navigate (previously stuck on t=0.00 with no visible action), and the LLM answer prompt now properly refuses ("not found" rather than fabricating). Backend strips [N] citation tokens before sending answers to the LLM judge so they don\'t pollute scores. Implementation surfaced a deeper finding: retrieval recall is only 15% (28 of 48 evaluation questions trigger an honest "not found" refusal) and the gpt-5-nano LLM judge scores correctly-phrased Mandarin refusals at only 0.51 (rubric should be 1.0). Together these two factors depressed our Faithfulness score, but neither is caused by R2.1\'s UI improvements — R3.x retrieval work plus R1.3 judge recalibration are the real fixes, both tracked in the roadmap with a case study attached.',
    },
    summaryBullets: {
      zh: [
        '搜尋結果加上 indigo 加粗加底線高亮、前後 2 句上下文、AI 摘要 60 字「展開」',
        '「跳到這段內容」按鈕 + URL `?episode_id=&t=` deep-link 可分享 / 可加書籤 / reload 還在',
        '節目簡介卡按鈕改「打開該集」、URL 邊界錯誤靜默回首頁、LLM 加拒答模式',
        'Faithfulness 從 0.71 降到 0.50（軟 gate ≥ 0.50 通過）— RCA 證實是 retrieval 跟 judge 問題，R3.x + R1.3 後續解',
      ],
      en: [
        'Result cards: indigo bold-underline highlights, 2-sentence before/after context, 60-char AI summary with Show More toggle',
        '"Jump to transcript" button + `?episode_id=&t=` URL deep-link — shareable, bookmarkable, reload-safe',
        'Description-source results now read "Open episode"; edited URLs silent-fallback to home; LLM prompt now refuses honestly',
        'Faithfulness dropped 0.71 → 0.50 (soft gate ≥ 0.50 passed) — RCA shows it\'s retrieval + judge, not R2.1 itself; R3.x + R1.3 are the real fixes',
      ],
    },
  },

  // ─── v1.5 — Browsable Release Log (5/09) ───
  {
    date: '2026-05-09', slug: 'release-log-collapsible', milestone: 'v1.5', tag: 'ui',
    title: {
      zh: '更新日誌好讀了：先看重點摘要、想看細節再展開',
      en: 'Release Log, Now Browsable: Skim the Bullets, Expand for Detail',
    },
    summary: {
      zh: '到 v1.4 為止，更新日誌頁所有 entry 一次全展開，捲一輪要花不少時間，也不容易看出哪些版本跟你相關。從這版開始，每筆 entry 預設收合，只露出版本、日期、標題、tag、跟 2-4 個重點 bullet——一眼掃過去就能挑出感興趣的展開讀。點 header 任意位置（或鍵盤 Tab + Enter / Space）切換收合；也支援直接貼網址 anchor（如 `/release-log#r3-1-hybrid-retrieval`）自動展開那筆 + 滾動到位。順手把過去 36 筆舊 entry 的重點 bullet 也補齊（其中 3 筆內容太單薄就不補，避免冗餘）。',
      en: 'Through v1.4, every release log entry rendered fully expanded by default — scrolling through the page took a while and it was hard to spot what was relevant to you. Starting now, entries default to collapsed: only the version, date, title, tag, and 2-4 summary bullets show. Skim the bullets, click any header (or Tab + Enter / Space) to expand the one you care about. URL anchors still work (e.g. `/release-log#r3-1-hybrid-retrieval` auto-expands and scrolls into view). Also backfilled summary bullets for 36 prior entries (3 trivial ones intentionally skipped to avoid filler).',
    },
    summaryBullets: {
      zh: [
        '每筆 entry 預設收合，header 露出 2-4 個重點 bullet 方便快速掃讀',
        '點 header 或鍵盤 Tab + Enter / Space 展開、URL anchor 自動展開到位',
        '舊 36 筆 entry 一併補齊重點 bullet，3 筆太單薄不補',
      ],
      en: [
        'Entries collapse by default; headers show 2-4 summary bullets for quick scanning',
        'Click header or Tab + Enter / Space to expand; URL anchors auto-expand and scroll',
        'Backfilled bullets for 36 older entries; 3 trivial ones skipped to avoid filler',
      ],
    },
  },

  // ─── v1.4 — Hybrid Retrieval (5/08) ───
  {
    date: '2026-05-08', slug: 'r3-1-hybrid-retrieval', milestone: 'v1.4', tag: 'enhancement',
    title: {
      zh: '搜尋變雙保險：embedding + 關鍵字 + 節目簡介都進來找',
      en: 'Search Now Has Three Sources: Embeddings + Keywords + Show Notes',
    },
    summary: {
      zh: '原本問問題只靠 embedding（語意相似度），中文短詞訊號弱、節目主自創的字（迪拉胖、顏社、蘴月食堂）幾乎抓不到。從這版開始，搜尋同時跑語意 + 關鍵字（jieba 中文分詞 + Postgres tsvector），用 RRF 演算法把兩邊融合排序——關鍵字認得「迪拉胖」是一個整體不會被切成「迪/拉/胖」。順帶把節目主在 RSS 寫的每集簡介也丟進索引（餐廳列表、來賓名、主題 bullets），entity 密度比逐字稿還高，有時還比較準（EP143 逐字稿被 Whisper 聽成「楓月食堂」，簡介寫對「蘴月食堂」）。後台多了個分詞詞典管理介面，admin 可以隨時加詞 → 按 Reload 後 backend / worker / dispatcher / beat 4 個 service 同步生效。實機 eval 在 48 題 golden set 上，episode-level 命中率從 2.4% 拉到 23.8%（10 倍），Recall@20 從基本沒有拉到 62%——意思是答案大多在前 20 名裡，下一步 R3.2 要解決的就是怎麼把對的集數排到前 5 名。順手修了 chunk 重切時對 Whisper 空白段落造成的 OpenAI API 400 errors，重切完所有 transcript_chunks 都有關鍵字索引（98K 筆 100% coverage）。',
      en: 'Search used to be embedding-only (semantic similarity). Short Chinese tokens have weak embedding signal, and the host\'s coined names (迪拉胖, 顏社, 蘴月食堂) were almost untouchable. Starting this release, every query runs semantic AND lexical (jieba Chinese tokeniser + Postgres tsvector) and fuses the two via RRF — the lexical side recognises "迪拉胖" as one token, not three characters. Bonus: each episode\'s RSS show notes (restaurant lists, guest names, topic bullets) now feeds a separate index — entity-dense, sometimes more accurate than the transcript itself (Whisper mishears EP143\'s 蘴月食堂 as 楓月食堂; the show notes have the correct character). Admin gets a tokenizer dictionary tab — add a term, click Reload, and backend / worker / dispatcher / beat all pick it up live. On the 48-item golden set, episode-level Recall@5 jumped from 2.4% to 23.8% (10×), and Recall@20 = 62% — so the right episode is almost always in the retrieval pool. R3.2\'s job is getting it into the top 5. Bundled fix: rebuild_chunks now drops whitespace-only chunks (Whisper sometimes emits empty segments) that were rejecting the entire embedding batch. All 98K transcript chunks now have lexical index coverage.',
    },
    summaryBullets: {
      zh: [
        '搜尋同時跑語意 + 中文分詞關鍵字，節目主自創字（迪拉胖、蘴月食堂）抓得到了',
        '節目主寫的每集簡介也納入索引，entity 密度高、有時比逐字稿還準',
        '48 題 golden set Recall@5 從 2.4% 拉到 23.8%（10×），Recall@20 = 62%',
      ],
      en: [
        'Every query now runs semantic + Chinese-tokenised keyword search, fused via RRF — host-coined names finally findable',
        'Per-episode RSS show notes feed a separate entity-dense index, sometimes beating the transcript itself',
        'Episode-level Recall@5 jumped 2.4% → 23.8% (10×) on the 48-item golden set; Recall@20 = 62%',
      ],
    },
  },

  // ─── v1.3 — Off-site Encrypted Backup (5/07) ───
  {
    date: '2026-05-07', slug: 'db-backup', milestone: 'v1.3', tag: 'enhancement',
    title: {
      zh: '每天自動備份，異地離線、加密、月度自動驗證',
      en: 'Daily Encrypted Off-site Backup, Auto-Verified Monthly',
    },
    summary: {
      zh: '到目前為止，整套系統的安全網就是「Zeabur 那邊的資料庫不要壞」。從今天開始，每天凌晨會自動把整個資料庫拉出來、用公鑰加密，再上傳到另一家雲端（Cloudflare R2，跟 Zeabur 解耦）。每月 1 號 GitHub Actions 自己會拉最新一份月度備份做還原測試 + 跑健康檢查 SQL，過了寄成功信、沒過寄警告信——「沒測過的備份等於沒備份」。保留策略：最近 7 天每日 + 最近 4 週每週日 + 最近 12 個月每月一份，總共約 23 份在線。私鑰雙地保管（管理員本機 + 密碼管理器）；GitHub Actions 用獨立 keypair，本機萬一被攻陷不會波及。月成本約 $1。完整還原 runbook 寫在 docs/disaster-recovery.md，凌晨被叫起來照做即可，承諾 24 小時內的資料可救（RPO ≤ 24h）、30 分鐘內可救完（RTO ≤ 30 min）。順手修了個資安問題：原本 pg_dump 把資料庫密碼放在指令參數，會出現在 worker container 的 /proc/cmdline——改用 PGPASSWORD 環境變數，並 rotate 了 prod 密碼。',
      en: 'Until today, the entire safety net was "Zeabur\'s managed Postgres better not break." Starting now, the whole database gets pulled, public-key encrypted, and uploaded to a different cloud provider (Cloudflare R2, decoupled from Zeabur) every morning at 03:00 UTC. On the 1st of each month, GitHub Actions automatically pulls the latest monthly backup, runs a real pg_restore into an ephemeral DB, and runs sanity SQL — pass = OK email, fail = alert email. "Untested backups are broken backups." Retention: 7 daily + 4 Sundays + 12 monthly = ~23 versions live. Private key kept in two places (admin laptop + password manager); GitHub Actions uses a separate keypair so a laptop compromise doesn\'t leak prod backups. Monthly cost ≈ $1. Full restore runbook lives in docs/disaster-recovery.md. Commitments: RPO ≤ 24h, RTO ≤ 30 min. Bundled fix: pg_dump used to leak the DB password through process argv (visible in worker /proc/cmdline) — switched to PGPASSWORD env, and rotated the prod password.',
    },
    summaryBullets: {
      zh: [
        '每日加密備份上傳到 Cloudflare R2，跟 Zeabur 解耦異地保管',
        '每月 1 號自動還原 + 健康檢查，沒測過的備份等於沒備份',
        'RPO ≤ 24 小時、RTO ≤ 30 分鐘，月成本約 $1',
        '順手修掉 pg_dump 密碼洩漏到 /proc/cmdline 的資安問題',
      ],
      en: [
        'Daily encrypted snapshots ship to Cloudflare R2, decoupled from Zeabur',
        'Monthly auto-restore + sanity SQL — untested backups are broken backups',
        'RPO ≤ 24h, RTO ≤ 30 min, ~$1/month all in',
        'Bundled fix: pg_dump password no longer leaks via /proc/cmdline',
      ],
    },
  },

  // ─── v1.2 — RAG Accuracy Baseline (5/07) ───
  {
    date: '2026-05-07', slug: 'r1-eval-framework', milestone: 'v1.2', tag: 'enhancement',
    title: {
      zh: '現在我們知道 AI 答得多準（或多不準）',
      en: 'We Now Know How Accurate the AI Actually Is (or Isn\'t)',
    },
    summary: {
      zh: '我們上了一套自動化評測流程：手寫 10 個我們已經知道答案的「標準題」，再用 AI 配合人工審核生出 38 個延伸題，每次只要改了 RAG 邏輯，這 48 題就能跑一輪、量化告訴我們「答對片段的比率」是進步還是退步。第一輪 baseline 跑出 Recall@5 只有 2.4% ——意思是 AI 從這個節目 162 集裡，找到正確逐字稿片段的機率不到三十分之一。聽起來很糟，事實上也很糟，但這正是這套工具的價值：以前只能憑感覺說「不準」，現在拿到一個明確的數字可以追。下一步是把混合檢索（語意 + 中文分詞 BM25 關鍵字）做進去，做完之後我們可以直接告訴你進步了百分之幾。順手也加了後台「過去評測歷史」頁，跟一個每月發信的提醒任務，提醒哪些節目該重跑 baseline 了。',
      en: 'We shipped an automated eval pipeline: 10 hand-written "we-know-the-answer" sentinel questions plus 38 LLM-generated + human-audited follow-ups. Every time we touch the RAG layer, this 48-question battery runs and tells us — in numbers — whether the AI got better or worse at finding the right transcript chunks. First baseline came back with Recall@5 = 2.4%: the AI surfaces the correct chunk less than 1 time in 30 across this 162-episode show. That\'s as bad as it sounds, but that\'s exactly the point of having the metric — before this we could only say it "felt inaccurate." Next up: hybrid retrieval (semantic + Chinese-tokenized BM25 keyword) goes in, and we\'ll be able to tell you the improvement in percent. Also bundled: an admin "past eval runs" tab and a monthly reminder email flagging which shows are due for a re-run.',
    },
    summaryBullets: {
      zh: [
        '建立 48 題 golden set，每次改 RAG 都能跑分量化進步',
        'Baseline Recall@5 = 2.4%，從「感覺不準」變成有明確數字可追',
        '後台多了過去評測歷史頁 + 每月重跑提醒信',
      ],
      en: [
        '48-question golden set scores every RAG change in numbers',
        'Baseline Recall@5 = 2.4% — "feels inaccurate" now has a real metric',
        'Admin gets eval history tab + monthly re-run reminder email',
      ],
    },
  },

  // ─── v1.1 — Collecting Answer Quality Feedback (5/05) ───
  {
    date: '2026-05-05', slug: 'r1-ui-feedback-infra', milestone: 'v1.1', tag: 'feature',
    title: {
      zh: '對 AI 回答給回饋',
      en: 'Give Feedback on AI Answers',
    },
    summary: {
      zh: '每則 AI 統整回答下方多了 👍 / 👎 兩個按鈕。覺得答對了給讚，覺得不準時點倒讚並留下你想說的話（可空白）。點開回答中引用的逐字稿片段時，系統也會偷偷記下來——這些訊號會用來幫我們找出 AI 容易答錯的問題類型，下一階段拿去做答題品質的回歸測試。順手調整：首頁節目卡片回到完整版本（封面、語言、進度條、RSS 連結都齊全），登入頁的文案也修得更直白——「瀏覽逐字稿、看相關段落都不用登入。只有請 AI 統整回答需要登入使用額度。」',
      en: 'Each AI summary answer now has 👍 / 👎 buttons below it. Tap thumbs-up if it nailed the question; tap thumbs-down to optionally leave a note about what was wrong. The system also quietly records when you click into a citation transcript — these signals help us spot which kinds of questions the AI tends to fumble, so the next step (an automated answer-quality regression suite) has real cases to learn from. Bundled tweaks: the landing page show cards return to the full layout (cover art, language, progress bar, RSS link), and the login prompt copy is now plainer: "Browsing transcripts and matched segments needs no login. Only \'Ask AI to summarize\' requires login and uses your quota."',
    },
    summaryBullets: {
      zh: [
        '每則 AI 回答可按 👍 / 👎，倒讚可留言說哪裡不準',
        '點開引用片段也會被默默記錄，作為下一步答題品質回歸的素材',
        '首頁節目卡片回到完整版（封面、語言、進度條、RSS）',
      ],
      en: [
        'Thumbs-up / thumbs-down on every AI answer, with optional note on misses',
        'Citation clicks logged quietly to feed the upcoming answer-quality regression suite',
        'Landing show cards restored to the full layout (cover, language, progress, RSS)',
      ],
    },
  },

  // ─── v1.0 — Public Launch: Freemium Mode (5/04) — infra ───
  {
    date: '2026-05-04', slug: 'custom-domain-and-zsend', milestone: 'v1.0', tag: 'enhancement',
    title: {
      zh: '搬到自有網域 podcastrag.app + 信件服務上線',
      en: 'Custom Domain podcastrag.app + Email Notifications Live',
    },
    summary: {
      zh: '從 zeabur.app 共享子域搬到自有網域：前端 app.podcastrag.app、後端 api.podcastrag.app（Let\'s Encrypt 自動 SSL）。網域透過 Zeabur registrar 直接購買（$14.99/年，自動續訂），DNS 由 Cloudflare 託管。同時開通 ZSend 信件服務並驗證 podcastrag.app 為 sending domain（SES 東京 region），quota 申請通知信現在會從 noreply@podcastrag.app 實際寄出（早上 5 點 + 下午 5 點各一次彙整）。舊 zeabur.app 子域仍保留可用，兩個網域並存讓既有書籤不會壞。實作中也順手修了一個 ZSend API URL 的 bug（之前是用猜的，實際應該是 api.zeabur.com/api/v1/zsend/emails 而不是 zsend.zeabur.app/api/v1/send）。',
      en: 'Migrated off zeabur.app shared subdomains to a custom domain: frontend at app.podcastrag.app, backend at api.podcastrag.app (Let\'s Encrypt SSL auto-issued). Bought through Zeabur\'s registrar ($14.99/yr with auto-renew) with Cloudflare-managed DNS. Also onboarded ZSend with podcastrag.app as a verified sending domain (SES Tokyo region) — quota request digest emails now actually deliver from noreply@podcastrag.app (twice daily at 5am + 5pm Taipei time). Old zeabur.app subdomains remain functional so existing bookmarks keep working. Caught a ZSend API URL bug along the way (the URL was a guess: it\'s actually api.zeabur.com/api/v1/zsend/emails, not zsend.zeabur.app/api/v1/send).',
    },
    summaryBullets: {
      zh: [
        '搬到自有網域 app.podcastrag.app / api.podcastrag.app（Let\'s Encrypt SSL）',
        'ZSend 信件服務上線，quota 申請通知信實際從 noreply@podcastrag.app 寄出',
        '舊 zeabur.app 子域並存保留，既有書籤不會壞',
      ],
      en: [
        'Live on custom domain: app.podcastrag.app / api.podcastrag.app with auto SSL',
        'ZSend onboarded — quota digest emails now actually deliver from noreply@podcastrag.app',
        'Old zeabur.app URLs still work, so no bookmarks break',
      ],
    },
  },

  // ─── v1.0 — Public Launch: Freemium Mode (5/04) ───
  {
    date: '2026-05-04', slug: 'freemium-onboarding', milestone: 'v1.0', tag: 'feature',
    title: {
      zh: '公開上線：freemium 模式',
      en: 'Public Launch: Freemium Mode',
    },
    summary: {
      zh: '從「全站登入才能用」改成「先讓人看到價值再要登入」。新的首頁直接秀出三個收錄節目（曼報、壹加壹電台、這又沒有很屌）+ 真實的索引統計（553 集、247 已轉錄）+ 一個馬上能用的搜尋框；瀏覽逐字稿、看相關段落都不用登入，每個 IP 每天 20 次免費搜尋打底（embedding 成本可控）。只有「請 AI 整段統整回答」要登入才解鎖，新使用者用 Google 一鍵登入立刻拿到 30 次免費 quota。Quota 用完不會自動補充，使用者主動透過 QueryPage 上方的「申請更多額度」按鈕送理由給 admin；admin 後台多了「Quota 申請」分頁可一鍵核准（自由設定加值數量）或拒絕。Beat 排程每天兩次（UTC 09:00 / 21:00）把 pending 申請彙整成一封 email 經 ZSend 寄給 admin（要先開通 ZSend，沒開通時 task 直接 no-op log）。對既有登入使用者完全相容（quota_remaining 不會被改）。',
      en: 'Switched from "log in to use anything" to "see the value before signing up." The new home page surfaces all three indexed shows (曼報, 壹加壹電台, 這又沒有很屌), live indexing stats (553 episodes, 247 transcribed), and an immediately-usable search box. Browsing transcripts and seeing matched segments stays free — anonymous visitors get 20 free segment searches per IP per day (embedding cost stays bounded). Only the AI-generated summary answer requires login. New users sign in with Google in one click and get 30 free queries; quota does not auto-refill. When depleted, users hit "Request more quota" on QueryPage to send a reason to admin. The admin panel grows a "Quota Requests" tab for one-click approve (free-form amount) or reject. A beat task digests pending requests into one email twice daily (UTC 09:00 / 21:00) via ZSend (no-ops with a log when ZSend is not yet provisioned). Fully backwards-compatible with existing logged-in users — their quota_remaining is preserved.',
    },
    summaryBullets: {
      zh: [
        '訪客不用登入即可瀏覽逐字稿、看相關段落（每 IP 每天 20 次免費搜尋）',
        '只有「請 AI 統整回答」要登入，新使用者 Google 一鍵登入拿 30 次 quota',
        'Quota 用完可送理由申請更多，admin 後台一鍵核准或拒絕',
        '每天兩次彙整 pending 申請成一封信寄給 admin（透過 ZSend）',
      ],
      en: [
        'Anonymous visitors can browse transcripts and segments (20 free searches per IP/day)',
        'Only the AI summary answer needs login — Google sign-in gives new users 30 free queries',
        'Out of quota? Send a reason; admin approves or rejects in one click',
        'Pending requests digest into one email twice daily via ZSend',
      ],
    },
  },

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
    summaryBullets: {
      zh: [
        '摘要任務卡超過 10 分鐘自動重置 + 重新排隊，不再卡整天',
        'Worker 被 SIGKILL/OOM 也會把 row 標 failed 並寫錯誤訊息',
        '後台徽章 hover 顯示具體錯誤，排查更直接',
      ],
      en: [
        'Stuck "running" summaries auto-reset and re-queue after 10 min',
        'Worker SIGKILL / OOM now marks the row failed with the exception text',
        'Admin badge reveals the underlying error on hover for fast debugging',
      ],
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
    summaryBullets: {
      zh: [
        '每集自動產 80-150 字繁中摘要，取代 RSS 廣告文案',
        '失敗對使用者完全透明，自動 fallback 顯示原 RSS 描述',
        'Admin 可單集重跑 + 一鍵批次補摘要既有 360 集（約 $0.7）',
      ],
      en: [
        'Every episode auto-generates an 80-150 char summary, replacing RSS marketing copy',
        'Failures fall back silently to the RSS description — no spinner, no error',
        'Admin gets per-episode regenerate + one-click backfill for the 360-episode catalog (~$0.7)',
      ],
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
    summaryBullets: {
      zh: [
        '取代 14 天就過期的 cookie 檔案，自動化驗證不用再手動重抓',
        '只有設了 token env 才會註冊，沒設的部署連 404 都不洩漏',
        'HMAC 比對 + 15 分鐘 session + IP 失敗率限，audit log 全紀錄',
      ],
      en: [
        'Replaces the 14-day cookie file — no more manual re-login for E2E verification',
        'Endpoint only exists when E2E_LOGIN_TOKEN is set; otherwise a normal 404',
        'HMAC compare + 15-min session cap + per-IP rate-limit, fully audit-logged',
      ],
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
    summaryBullets: {
      zh: [
        'API 金鑰集中管理，5 個 AI 處理步驟各自挑 key + model',
        '轉錄供應商可在 OpenAI Whisper 與本地 faster-whisper 間切換，不用 redeploy',
        '為下一版「每集 AI 摘要」鋪好 summary step 的位子',
      ],
      en: [
        'Centralised API key registry; five AI steps each pick their own key + model',
        'Switch transcription provider (OpenAI Whisper vs local faster-whisper) from UI, no redeploy',
        'Lays the summary-step groundwork for the upcoming per-episode AI summary',
      ],
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
    summaryBullets: {
      zh: [
        'Redeploy 後 1-3 分鐘內就把卡住的轉錄推回排隊，不用等 30 分鐘',
        '修掉強制取消會卡住排隊額度的隱藏 bug',
        'dispatcher / beat 不會再因為缺登入 env 啟動失敗',
      ],
      en: [
        'Stuck transcriptions re-queue within 1-3 min of redeploy instead of 30 min',
        'Fixed hidden force-cancel bug that left a throttle slot occupied',
        'Dispatcher / beat no longer crash on startup when auth env vars are unset',
      ],
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
    summaryBullets: {
      zh: [
        '更新日誌改成單條垂直時間軸，最新在上',
        '佇列「進行中」分頁 running 在上，pending 帶 1/2/3 排隊編號',
        '空節目時 admin 一鍵跳後台節目管理',
      ],
      en: [
        'Release Log redesigned as a vertical timeline, newest first',
        'Active queue tab puts running rows on top with 1/2/3 position badges',
        'Empty PodcastSelect routes admins straight to show management',
      ],
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
    summaryBullets: {
      zh: [
        '砍掉寫死帳密 modal，改成 Google 一鍵登入',
        '一般使用者 100 次預設 quota，後台可加值',
        'Admin 權限只給 ADMIN_EMAILS 白名單，跨站請求 CSRF + Origin 雙保險',
      ],
      en: [
        'Hardcoded admin modal replaced with Google SSO sign-in',
        'Members get 100 queries by default; admin can top up',
        'Admin role only for ADMIN_EMAILS allowlist; CSRF + Origin block cross-site requests',
      ],
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
    summaryBullets: {
      zh: [
        '新增「更新日誌」分頁，過去 archived changes 翻成白話雙語條目',
        '按里程碑分組，一眼看出系統的演進軌跡',
        '獨立簡報頁 13 張 slide，可同步產出 .pptx',
      ],
      en: [
        'New Release Log tab translates archived changes into plain bilingual entries',
        'Grouped by milestone for at-a-glance system evolution',
        'Standalone 13-slide presentation page, exportable as .pptx',
      ],
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
    summaryBullets: {
      zh: [
        '768px 斷點：手機版漢堡選單、單欄表單、抽屜式集數面板',
        '後台佇列拖曳排序在手機改用上下箭頭按鈕',
      ],
      en: [
        '768px breakpoint adds hamburger menu, single-column forms, drawer episode panel',
        'Queue reorder switches to up/down buttons on mobile',
      ],
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
    summaryBullets: {
      zh: [
        '外部 API 失敗顯示具體中文訊息，不再丟「Failed to fetch」',
        '修正 unhandled exception 下 CORS header 漏寫的問題',
      ],
      en: [
        'External API failures now show specific localized messages, not "Failed to fetch"',
        'Fixes missing CORS headers on unhandled exceptions',
      ],
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
    summaryBullets: {
      zh: [
        '佇列分成三個子分頁：排隊中+執行中 / 完成 / 失敗+取消',
        '排程砍掉 hourly，週排程可選星期幾並即時顯示「每週X 觸發」',
      ],
      en: [
        'Queue split into three sub-tabs: active / done / closed',
        'Hourly removed; weekly schedules pick a day-of-week with live preview hint',
      ],
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
    summaryBullets: {
      zh: [
        '後台新增「轉錄序列」分頁，逐筆看每個任務狀態',
        '支援取消 / 強制取消 / 重試 / 忽略 / 拖曳調整排隊順序',
        '可設定平行轉錄上限',
      ],
      en: [
        'New admin tab lists every queue row by status',
        'Cancel, force-cancel, retry, ignore, and drag-reorder per row',
        'Configurable concurrency cap',
      ],
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
    summaryBullets: {
      zh: [
        '每分鐘掃描卡死的轉錄任務，超過 30 分鐘自動標 failed',
        '釋放排隊槽位，避免 worker redeploy 後佇列永遠塞住',
      ],
      en: [
        'Per-minute sweep marks transcriptions stuck > 30 min as failed',
        'Frees the slot so a worker redeploy never permanently freezes the queue',
      ],
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
    summaryBullets: {
      zh: [
        'Worker 改 concurrency=3，可同時跑 3 集真平行轉錄',
        '新增「強制取消」按鈕，能中止已啟動的轉錄任務',
      ],
      en: [
        'Worker concurrency=3 — three episodes transcribe in true parallel',
        'New "force cancel" button can terminate already-running transcriptions',
      ],
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
    summaryBullets: {
      zh: [
        '排程從「死資料」變成真 cron，到時間自動拉新集數入隊',
        'Celery Beat 每分鐘掃排程表，佇列改由 DB 表驅動',
        '所有操作可原子化記錄，狀態不再不一致',
      ],
      en: [
        'Schedules become real cron — Beat scans every minute and enqueues new episodes',
        'Queue is now DB-driven for atomic state transitions',
        'No more state drift between schedule config and actual runs',
      ],
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
    summaryBullets: {
      zh: [
        '排程頁卡片可展開看每集 pending / processing / completed / failed 數',
        '新增「外部 API 狀態」分頁，OpenAI Whisper / Chat / Embedding 健康一目了然',
        '錯誤分類顯示，問題追查更快',
      ],
      en: [
        'Per-show cards expand to show pending / processing / completed / failed counts',
        'New "External API Status" tab tracks OpenAI Whisper / Chat / Embedding health',
        'Errors are categorized so root cause is obvious',
      ],
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
    summaryBullets: {
      zh: [
        '砍掉 RSS 寫死 200 集上限，預設不再截斷',
        '按「更新節目集數」即可補回壹加壹電台缺失的 51 集',
      ],
      en: [
        'Hardcoded 200-episode RSS cap removed; default no longer truncates',
        '"Update episodes" backfills the 51 missing entries from 壹加壹電台',
      ],
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
    summaryBullets: {
      zh: [
        '排程不再只能刪除重建，新增「編輯」modal 可改頻率 / 時間 / 模型 / 上限',
        '「立刻執行」按鈕只轉最新 N 集，不會誤觸全部 backlog',
      ],
      en: [
        'Schedules now editable in a modal — change frequency, time, model, or cap',
        '"Run now" button transcribes only the latest N episodes, not the full backlog',
      ],
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
    summaryBullets: {
      zh: [
        '「同步集數」/「同步所有」改名為「更新節目集數」/「轉錄未完成集數」，意圖更明確',
        '加入 Gmail 風 checkbox 批次選取',
        '批次轉錄前跳一次確認，避免誤觸燒錢',
      ],
      en: [
        '"Sync" verbs renamed for clarity — RSS refresh vs transcription is now obvious',
        'Gmail-style checkbox selection for batch operations',
        'Batch transcription now requires explicit confirm before spending OpenAI credit',
      ],
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
    summaryBullets: {
      zh: [
        '暫時錯誤（5xx、rate limit、timeout）自動重試 3 次，10s → 60s → 300s 退避',
        'Redis 全域並發限制，避免「同步所有」一次塞爆 worker',
      ],
      en: [
        'Transient errors auto-retry 3× with 10s → 60s → 300s exponential backoff',
        'Redis-based global concurrency cap prevents "sync all" from overloading the worker',
      ],
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
    summaryBullets: {
      zh: [
        '右側集數列表接上真實 API，不再是 mock 資料',
        'RAG 改用結構化輸出，只顯示實際被引用的片段',
        '點擊引用 Badge 跳到逐字稿並高亮對應時間段',
      ],
      en: [
        'Episode panel wired to real API instead of mock data',
        'RAG structured output surfaces only actually-cited chunks',
        'Click a citation to jump to the transcript with the timestamp highlighted',
      ],
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
    summaryBullets: {
      zh: [
        '超過 1 小時的 podcast 不再讓 worker 記憶體飆到 1.5-2 GB 被 OOM 殺掉',
        '改用 ffmpeg stream copy 切段，記憶體常數、Zeabur 4GB plan 穩定運行',
      ],
      en: [
        '1-hour+ podcasts no longer spike worker memory to 1.5-2 GB and trigger OOM',
        'Switched to ffmpeg stream-copy chunking — constant memory, stable on Zeabur 4GB',
      ],
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
    summaryBullets: {
      zh: [
        '後台節目卡片新增刪除 / 同步集數 / 移除排程三個操作按鈕',
        '刪除前跳確認 modal，避免誤觸 cascade 刪光所有逐字稿',
      ],
      en: [
        'Show cards gain delete / sync / unschedule action buttons',
        'Delete requires confirm modal to prevent accidental transcript cascade-delete',
      ],
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
    summaryBullets: {
      zh: [
        '首頁從 4 個寫死 mock 改成 GET /shows 真實資料',
        '每個節目卡片顯示已轉錄集數的進度條',
        '補上 loading / error / empty 三種狀態',
      ],
      en: [
        'Home swaps 4 hardcoded mock shows for live GET /shows data',
        'Per-show transcribed-count progress bars',
        'Loading / error / empty states all wired up',
      ],
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
    summaryBullets: {
      zh: [
        'RAG 對話查詢正式上線：embedding + pgvector + LLM 帶引用回答',
        '支援多輪對話（5 輪滑動視窗）+ Search 模式直接回原文片段',
        '後台可切換 Answer / Rewrite 模型',
      ],
      en: [
        'RAG conversational query goes live: embedding + pgvector + cited answers',
        'Multi-turn dialog (5-window memory) + search mode for raw chunks',
        'Admin can swap Answer / Rewrite models on the fly',
      ],
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
    summaryBullets: {
      zh: [
        '突破 OpenAI Whisper 25MB 單檔上限，超過自動切段',
        '分批呼叫並合併結果、調整時間軸，使用者完全無感',
      ],
      en: [
        'Bypasses OpenAI Whisper 25MB single-file limit via auto-chunking',
        'Batched uploads merged with corrected timestamps — fully transparent',
      ],
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
    summaryBullets: {
      zh: [
        '音檔下載到 R2，Celery worker 跑 Whisper 產出帶時間戳的逐字稿',
        '支援 OpenAI Whisper API 與本地 faster-whisper 兩種模式',
        '新增 transcribe / get-transcript / batch transcribe 三組 API',
      ],
      en: [
        'Audio files land in R2; Celery workers produce timestamped transcripts',
        'Supports both OpenAI Whisper API and local faster-whisper',
        'New transcribe / get-transcript / batch-transcribe APIs',
      ],
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
    summaryBullets: {
      zh: [
        '貼 RSS URL 即可匯入真實節目，取代寫死的 mock 資料',
        '解析 RSS 2.0 + iTunes 延伸欄位，寫入 shows 與 episodes 表',
        '提供完整 CRUD / sync / list 節目 API',
      ],
      en: [
        'Paste an RSS URL to import a real podcast — no more mock data',
        'Parses RSS 2.0 + iTunes fields into shows / episodes tables',
        'Full CRUD / sync / list APIs included',
      ],
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
    summaryBullets: {
      zh: [
        'FastAPI 應用骨架 + PostgreSQL schema（節目 / 集數 / 逐字稿 / 向量）',
        '啟用 pgvector extension，Alembic migration 管 schema 變更',
        '健康檢查 endpoint 建好，後續所有功能的基礎',
      ],
      en: [
        'FastAPI skeleton + PostgreSQL schema (shows / episodes / transcripts / vectors)',
        'pgvector extension enabled; Alembic manages schema migrations',
        'Health-check endpoint in place — foundation for everything that follows',
      ],
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
