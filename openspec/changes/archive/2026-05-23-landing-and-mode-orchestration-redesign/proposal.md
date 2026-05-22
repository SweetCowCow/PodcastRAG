## Why

目前 PodcastRAG 的首頁與三模式（索引 / 語意 / 對話）體驗有四個明顯痛點：（1）`LandingPage` 與 `PodcastSelect` 分離，未登入者要先看 marketing 頁、登入後才能挑節目，且 landing 完全沒對三模式做使用情境教育；（2）`QueryPage` 對話 source 同時呈現 chip 與 card 兩區，畫面混亂、引用集數難以快速掃讀；（3）Lock card 目前僅一份文案，未區分「anonymous」與「quota exhausted」情境，且寫了不存在的「免費 / 重置時間」承諾，誤導使用者；（4）音訊播放器綁在單一 SourceCard 上，切到 `TranscriptPage` 或換段就被打斷，paragraph 是逐句呈現難以閱讀。本次改版要把首頁、模式編排、引用呈現、音訊播放、Lock card 一次收斂到同一個 information architecture 上。

## What Changes

- **HomePage 合併**：移除 `LandingPage.jsx` 與 `PodcastSelect.jsx` 分立的兩條路徑，新增 `HomePage.jsx` 同時承擔節目挑選 + 模式介紹（hero swap 視登入狀態切換）。
- **Mode trio 介紹區**：HomePage 中段新增三模式介紹卡（索引 / 語意 / 對話），純教育不可點，每張卡含 1 固定範例 + 額度標；行動端垂直 stack。
- **熱搜 chip**：在現有 `events` 表新增 `event_type='search_executed'`，每次語意 / 對話查詢成功時 emit；新增 `GET /shows/{id}/trending-queries?days=7` 回傳 7 日 cutoff ≥ 3 次的查詢字串，HomePage 節目卡與 QueryPage tab 列顯示 chip。
- **QueryPage 三 tab**：將原本 single-mode page 改成 `索引 / 語意 / 對話` 三 tab；索引 tab 本 change 僅 placeholder（backend 在 `keyword-index-mode` change 接），登入者預設對話 tab，未登入者預設索引 tab；切 tab 保留歷史輸入字串。
- **對話 source panel 整併**：取消既有 chip + card 雙區設計，改為單一 episode-grouped panel，標頭固定「答案參考來源（共 N 集 · M 段引用）」。
- **Lock card 重設計**：覆蓋對話答案區，分 (a) anonymous 與 (b) quota exhausted 兩態，文案見 design.md 中已定版內容；(b) 點 CTA 開啟既有 `QuotaApplyModal.jsx`，呼叫既有 `POST /quota-requests`。
- **Sticky audio player**：新增 `StickyAudioPlayer.jsx`，HTML5 native + 1.0 / 1.25 / 1.5x 速度，跨 `QueryPage` 與 `TranscriptPage` 共用同一個 instance，切頁不重播。
- **Paragraph aggregation**：新增 client-side util `aggregateParagraphs.js`，segment 間 ≥ 1.5 秒停頓視為段落切點，`TranscriptPage` 與對話 / 語意的 SourceCard 共用同一邏輯。
- **語意 mode hybrid C 渲染**：語意搜尋結果改為 flat list top-K（RRF 排序），同 episode 多 chunk 顯示「+N 同集」chip，每筆顯示相關度 bar。

## Non-Goals

- 索引 mode 的 backend endpoint、CTE SQL、sectioned 結果頁 V-Z 與兩色高亮 → 在另一個 change `keyword-index-mode` 處理；本 change 只開索引 tab 的 placeholder UI。
- Disabled user（auth callback 403 `ACCOUNT_DISABLED`）的申訴流程 → 拉到 follow-up change `disabled-user-appeal-flow`。本 change 的 Lock card 不處理 disabled 情境，僅 cover anonymous 與 quota exhausted 兩態。
- 後台 / Admin Dashboard 任何頁面、quota 自動補額 cron、付費升級流程。
- 既有 `quota_requests` 表 schema 與 `POST /quota-requests` endpoint 不動，只新接 Lock card CTA。
- 既有 RAG retrieval / RRF 演算法本身不動，只改前端渲染。

## Capabilities

### New Capabilities

- `home-page`: 合併後的首頁（節目挑選 + 三模式教育 + hero swap + 熱搜 chip），取代既有 landing-page + PodcastSelect 兩條路徑。
- `mode-orchestration-ui`: QueryPage 三 tab（索引 / 語意 / 對話）+ 預設 tab 規則 + 切 tab 字串保留 + 索引 tab placeholder。
- `lock-card-ui`: 對話模式內覆蓋答案區的 Lock card，含 anonymous / quota exhausted 兩態 + 接既有 QuotaApplyModal。
- `sticky-audio-player`: 跨 QueryPage / TranscriptPage 共用、不被切頁打斷的 HTML5 native 音訊播放器（含 1.0 / 1.25 / 1.5x 速度）。
- `paragraph-aggregation`: Client-side segment → paragraph 聚合 util（1.5s 停頓 threshold），供 TranscriptPage 與 SourceCard 共用。
- `trending-queries-api`: `GET /shows/{id}/trending-queries?days=7` 回傳 7 日內 cutoff ≥ 3 次的查詢字串清單。
- `semantic-mode-result-ui`: 語意模式結果改 flat list + 「+N 同集」chip + 相關度 bar 的 hybrid C 渲染。
- `conversation-source-panel`: 對話模式單一 episode-grouped source panel，取代既有 chip + card 雙區。

### Modified Capabilities

- `client-events`: 在 `events` 表的 `event_type` 接受值新增 `search_executed`，並定義其 payload schema。
- `landing-page`: 路由行為改為導向新的 `home-page` capability（landing-page spec 不再 own `/` 的 unauthenticated UI，只保留歷史 marketing 區塊或標記 deprecated）。

## Impact

- Affected specs: home-page（new）、mode-orchestration-ui（new）、lock-card-ui（new）、sticky-audio-player（new）、paragraph-aggregation（new）、trending-queries-api（new）、semantic-mode-result-ui（new）、conversation-source-panel（new）、client-events（modified）、landing-page（modified）。
- Affected code:
  - New:
    - src/HomePage.jsx
    - src/ModeTrioIntro.jsx
    - src/TrendingQueriesChips.jsx
    - src/StickyAudioPlayer.jsx
    - src/LockCard.jsx
    - src/ConversationSourcePanel.jsx
    - src/SemanticResultList.jsx
    - src/utils/aggregateParagraphs.js
    - backend/app/api/trending_queries.py
    - backend/app/services/trending_queries.py
  - Modified:
    - PodcastRAG.html
    - src/App.jsx
    - src/QueryPage.jsx
    - src/TranscriptPage.jsx
    - src/Shared.jsx
    - src/i18n.jsx
    - src/QuotaApplyModal.jsx
    - backend/app/api/events.py
    - backend/app/api/shows.py
    - backend/app/models/events.py
  - Removed:
    - src/LandingPage.jsx（合併進 HomePage.jsx）
    - src/PodcastSelect.jsx（合併進 HomePage.jsx）
