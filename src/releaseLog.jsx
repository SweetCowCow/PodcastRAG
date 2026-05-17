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
  'v1.0': { zh: 'v1.0 — 公開上線：freemium 模式',   en: 'v1.0 — Public Launch: Freemium Mode' },
  'v1.1': { zh: 'v1.1 — 收集回答品質回饋',         en: 'v1.1 — Collecting Answer Quality Feedback' },
  'v1.2': { zh: 'v1.2 — 量化 RAG 答題準確度基線',  en: 'v1.2 — RAG Accuracy Baseline, Measured' },
  'v1.3': { zh: 'v1.3 — 把資料背在保險上',         en: 'v1.3 — Putting Your Data on Insurance' },
  'v1.4': { zh: 'v1.4 — 混合檢索：找到節目主寫的關鍵字', en: 'v1.4 — Hybrid Retrieval: Catching the Host\'s Own Keywords' },
  'v1.5': { zh: 'v1.5 — 更新日誌變好讀',           en: 'v1.5 — Release Log, Browsable' },
  'v1.6': { zh: 'v1.6 — 搜尋結果看得更清楚',       en: 'v1.6 — Search Results, Now Readable' },
  'v1.7': { zh: 'v1.7 — 搜尋準度大幅提升',         en: 'v1.7 — Retrieval Quality, Materially Better' },
};

// Entries — newest milestone first; within each milestone newest date first.
const RELEASE_LOG = [
  // ─── v1.7 — Retrieval Quality Fix (5/13–5/18) ───
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
