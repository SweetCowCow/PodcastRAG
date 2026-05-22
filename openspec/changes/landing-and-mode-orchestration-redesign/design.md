## Context

PodcastRAG 目前的前端進入動線：未登入 → `LandingPage` → Google SSO → `PodcastSelect` → `QueryPage`（單一模式，原 chat-only）。本次 UI redesign 經 39 項拍版（A-AH）+ Lock card 7 題收斂後，要把首頁、模式編排、Lock card、source 呈現、音訊、paragraph 顯示一次重整。本 change 對應 Phase 1，與另一個 change `keyword-index-mode`（Phase 2，索引 backend）平行 propose。

現況技術約束：

- 前端為瀏覽器直跑 JSX（React 18 + Babel Standalone，無打包），共用 token 在 `src/Shared.jsx`。
- 已有 `events` 表（capability `client-events`），目前只接受 `event_type='citation_click'`，per-IP rate limit 60/min。
- 已有 `quota_requests` 表 + `QuotaApplyModal.jsx` + `POST /quota-requests` + admin 後台收件 + `quota_digest.py` cron，全鏈路可用。
- 認證走 Google SSO + session cookie + `/me` 解析；首次登入自動建 active user，黑名單檢查在 `backend/app/api/auth.py` raise 403 `ACCOUNT_DISABLED`。
- 已有 `LandingPage.jsx`（marketing hero）、`PodcastSelect.jsx`（卡片網格）、`QueryPage.jsx`（單模式對話 + chip + card source 雙區）、`TranscriptPage.jsx`（segment list）。

## Goals / Non-Goals

**Goals:**

- 首頁一頁解決「節目挑選 + 三模式教育」，無論是否登入都呈現完整節目卡片網格。
- 三模式（索引 / 語意 / 對話）成為一級導航概念，QueryPage 用 tab 切換、預設 tab 視登入狀態而定。
- Lock card 文案分情境（anonymous / quota exhausted），且不寫不存在的承諾（無「免費」、無「重置時間」字眼）。
- 對話 source 用單一 episode-grouped panel，語意 source 用 flat list + 同集 chip。
- 音訊播放橫跨頁面持續，paragraph 顯示按停頓聚合（1.5 秒 threshold）。
- 熱搜 chip 走既有 events 表延伸（不另開表），讓查詢 telemetry 自然累積。

**Non-Goals:**

- 不實作索引 mode 的 backend retrieval、SQL CTE、結果頁 V-Z 渲染（屬於 change `keyword-index-mode`）。
- 不實作 disabled user 申訴流程（屬於 follow-up change `disabled-user-appeal-flow`）。
- 不引入新的狀態管理函式庫（Redux / Zustand）；繼續用 React useState + context。
- 不改 RAG retrieval / RRF 演算法本身；只改前端渲染方式。
- 不做付費升級、自動補額 cron、付費管道相關 UI。
- 不重做後台任何頁面。

## Decisions

### 決策 1：HomePage 合併 LandingPage 與 PodcastSelect

採用 `HomePage.jsx` 單一元件，視 `AuthContext.user` 決定 hero 區塊內容（未登入：marketing hero + Google 登入 CTA；登入：問候語 + 個人額度條 + 推薦節目）。節目卡片網格不分登入狀態都呈現，未登入者點卡片進 QueryPage 後預設索引 tab。

**Alternatives considered**：

- 保留兩個元件、用 route 切換 → 維護兩套 layout、SEO 與首屏內容割裂，且 hero swap 邏輯仍要重寫，沒減少複雜度。
- 用 conditional render in App.jsx → App.jsx 已負責路由 + 後台 modal + 語言切換，再塞首頁邏輯會肥大。

### 決策 2：QueryPage 改三 tab、預設 tab 視登入狀態

`QueryPage.jsx` 頂端加入 `<ModeTabs>`（索引 / 語意 / 對話）。預設 tab 規則：登入者 → 對話；未登入者 → 索引。切 tab 時 input 字串保留（共用 controlled state `queryText`），歷史結果按 mode 分桶保留（不互相清空）。索引 tab 本 change 僅 placeholder（顯示「即將推出」+ 引導到語意/對話）；待 `keyword-index-mode` change ship 後接 endpoint。

**Alternatives considered**：

- 三個獨立 page route → 切 mode 要重新打 retrieval、loss input、loss scroll。
- Default tab 都用對話 → 未登入者一進去就撞 Lock card，違反「先讓人能用」原則。

### 決策 3：Lock card 兩態 + 接既有 QuotaApplyModal

`LockCard.jsx` 接受 `variant: 'anonymous' | 'quota_exhausted'` prop。Anonymous 顯示 🔒 + Google 登入按鈕 + 「先用語意搜尋」二級 CTA；quota_exhausted 顯示 ⏳ + 「申請更多次數」按鈕（onClick 開既有 `QuotaApplyModal`）+ 「先用語意搜尋」二級 CTA。文案不寫「免費 N 次」、不寫「X 月 X 日重置」，只說「登入後可使用 30 次」與「已達使用上限，如果還需要繼續用，可以說明用途申請額度」。

**Lock card 定版文案（zh）**：

狀態 a — Anonymous（覆蓋對話答案區）：

```
🔒
不想花時間重聽找答案？
登入後直接針對節目內容發問，自動為你交叉比對，整理重點回覆
[以 Google 登入]
或先用[語意搜尋]找找看相關片段
```

狀態 b — Quota exhausted：

```
⏳
已達使用上限
如果還需要繼續用，可以說明用途申請額度
[申請更多次數]  ← 開既有 QuotaApplyModal
或先用[語意搜尋]找找看相關片段
```

英文版由 `i18n.jsx` 同步提供，語意一致即可。

**Alternatives considered**：

- 統一一份「請登入或申請額度」文案 → 對 anonymous 來說「申請額度」毫無意義；對已登入額度用盡者來說「請登入」也是雜訊。
- Lock card 改成 inline banner → 對話答案區還是會跑出來、誤導 user 以為有用，違反「明確擋住」的目標。

### 決策 4：熱搜 chip 走既有 events 表

不開新表，沿用 `events`，將 `event_type` 接受值擴展為 `{citation_click, search_executed}`。`search_executed` payload schema：`{show_id: str, query_text: str, mode: "semantic" | "chat"}`（索引 mode 由 `keyword-index-mode` 接，本 change 先不 emit）。新增 `GET /shows/{id}/trending-queries?days=7` endpoint：SQL 對 `events` 表 `WHERE event_type='search_executed' AND payload->>'show_id'=:show_id AND created_at >= now() - interval ':days days' GROUP BY payload->>'query_text' HAVING count(*) >= 3 ORDER BY count(*) DESC LIMIT 10`。回傳 `[{query_text, count}]`。

**Alternatives considered**：

- 開 `search_logs` 新表 → 重複 telemetry 基礎設施。
- 即時計算用 Redis sorted set → 維運成本 + 額外依賴；目前查詢量小，DB GROUP BY 足夠。

### 決策 5：對話 source panel 整併為 episode-grouped

`ConversationSourcePanel.jsx` 取代既有 chip 列 + SourceCard 列雙區。標頭固定「答案參考來源（共 N 集 · M 段引用）」（N = unique episodes, M = total chunks），下方按 episode 分組，每組可展開 / 收合，組內列出該集被引用的段落（共用 SourceCard，內部用 `aggregateParagraphs.js` 做段落聚合）。

**Alternatives considered**：

- 保留 chip 區只移除 card 區 → user 仍要切換注意力，沒解決混亂。
- Flat list 不分組 → 同集多段時資訊重複（標題重複），失去 grouping 價值。

### 決策 6：Sticky audio player 跨頁共用 single instance

`StickyAudioPlayer.jsx` 掛在 `App.jsx` 的最外層（router 之外），透過 React Context `AudioPlayerContext` 暴露 `{currentEpisode, playFromTime(episode_id, time), pause, seek, setSpeed}`。`QueryPage` 與 `TranscriptPage` 內任何按鈕點「在這段播放」都呼叫同一個 context method；切頁不重新 mount `<audio>` element，因此音訊不斷。速度切換 1.0 / 1.25 / 1.5x 三檔，存到 localStorage `audio_speed`。

**Alternatives considered**：

- 每頁自己的 `<audio>` → 切頁就斷，違反目標。
- 用 portal 把 audio 元件 render 到 body → React 18 + Babel Standalone 環境用 portal 可行但測試成本高，掛 root 就夠。

### 決策 7：Paragraph aggregation client-side + 共用 util

新增 `src/utils/aggregateParagraphs.js`，input: `[{text, start_time, end_time, speaker, ...}]`，output: `[{paragraph_text, start_time, end_time, speaker, segment_ids[]}]`。規則：相鄰 segment 間 `start_time(next) - end_time(prev) >= 1.5` 即切段；speaker 變化也切段。`TranscriptPage` 與 `SourceCard` 共用，避免兩處邏輯漂移。

**Alternatives considered**：

- Backend 做 paragraph aggregation 後存表 → 已有 `transcript_segments`，再加一張 paragraph 表是 schema bloat；client side 純函式即可。
- 寫進 chunk builder → chunk builder 服務 RAG 檢索（30-60s middle region），語意不是 reading paragraph，職責不同。

### 決策 8：語意 mode 採 hybrid C 渲染（flat list + 同集 chip + 相關度 bar）

`SemanticResultList.jsx` 接 retrieval 回來的 top-K（已 RRF 排序），但顯示時做兩件事：(a) 若同一 episode 有 K 個 chunk，只顯示分數最高的一筆，其它收成 `+{K-1} 同集` chip（點 chip 展開）；(b) 每筆右側顯示相關度 bar（normalize RRF score 到 0-100%）。Bar 不顯示具體 score 數字（避免 user 誤判）。

**Alternatives considered**：

- Hybrid A（episode-grouped）→ 違反「就是要 flat 看分數排序」的需求。
- Hybrid B（flat 但無同集 chip）→ 重複噪音多。
- 顯示具體 RRF 數字 → 對非技術 user 無意義。

### 決策 9：Mode trio 介紹區不可點 + 1 固定範例

HomePage 中段三張卡（索引 / 語意 / 對話），每張僅顯示「適合什麼問題 + 1 固定範例 query + 額度標」。不可點（hover 也無 cursor: pointer），純教育。設計目的：讓使用者進 QueryPage 之前心裡有底，避免「以為對話會回答關鍵字查找」的期望落差。行動端（width < 768px）三卡垂直 stack。

**Alternatives considered**：

- 卡片可點直接帶 query 進 QueryPage → 過早 commit，且 1 個範例反而成限制。
- 把介紹放 footer / about 頁 → 教育力道太弱。

## Implementation Contract

### Behavior

- 使用者打開 `/` 時看到 `HomePage`；無論登入與否，節目卡片網格都呈現；hero 區塊依登入狀態 swap。
- 點任一節目卡 → 進 `QueryPage`，登入者預設對話 tab，未登入者預設索引 tab；切 tab 時上一個 tab 的輸入字串保留、結果保留。
- 對話 tab 在 `user === null` 或 `quota.remaining === 0` 時，答案區由 `<LockCard variant=...>` 完全覆蓋；其它 UI（tab、輸入框）仍可操作。
- 對話成功送出後，前端對 `POST /events` 寫一筆 `{event_type: "search_executed", payload: {show_id, query_text, mode: "chat"}}`；語意搜尋成功同樣寫，mode 為 `semantic`。
- 節目卡與 QueryPage tab 列調用 `GET /shows/{show_id}/trending-queries?days=7`，顯示回傳的 query chip（最多 5 個）；點 chip 把字串塞進輸入框並送出。
- 點任一 SourceCard 的播放按鈕 → 透過 `AudioPlayerContext.playFromTime(episode_id, start_time)` 播放，切頁不斷；速度 toggle 1.0 / 1.25 / 1.5x。
- TranscriptPage 與對話 / 語意 SourceCard 內的逐字稿區塊，皆用 `aggregateParagraphs(segments, { gap_threshold_seconds: 1.5 })` 結果渲染。

### Interfaces / Data shape

- **新 API**：`GET /shows/{show_id}/trending-queries?days=7`
  - Auth: 不需要（公開，但套用 events 既有 per-IP rate limit 60/min）。
  - Response 200：`{queries: [{query_text: str, count: int}], days: int, cutoff: int}`，最多 10 筆，按 count desc。
  - 無 query 達 cutoff（≥3）時回 `{queries: [], ...}`。
  - 無此 show 回 404。
- **events 擴展**：`POST /events` 接受 `event_type='search_executed'`，payload schema `{show_id: UUID, query_text: str (1-500 chars), mode: enum("semantic", "chat")}`，extra keys 回 422。
- **前端 AudioPlayerContext**：`{currentEpisodeId, currentTime, isPlaying, speed, playFromTime(episodeId, startSec), pause(), seek(sec), setSpeed(num)}`。
- **LockCard props**：`{variant: "anonymous" | "quota_exhausted", lang: "zh" | "en", onLogin?, onApplyQuota?, onTrySemantic?}`。
- **aggregateParagraphs**：純函式 `(segments: Segment[], opts?: { gap_threshold_seconds?: number = 1.5 }) => Paragraph[]`。

### Failure modes

- `GET /trending-queries` DB 失敗 → 回 500，前端 silently fallback 不顯示 chip 區。
- `POST /events` 寫 `search_executed` 失敗 → 不阻擋查詢結果回傳，前端 swallow 錯誤。
- AudioPlayerContext 在切頁瞬間 `<audio>` 暫時 unmount → 違反 contract；必須 mount 在 router 之外，初始 mount 後不可重新 mount。
- `aggregateParagraphs` 輸入空陣列 → 回空陣列，不 throw。
- Lock card variant 拿到未知值 → render fallback「請登入」訊息，不 crash。

### Acceptance criteria

- 手動驗證清單（記入 tasks.md）：
  1. 未登入打開 `/` 看到 marketing hero + 節目卡片 + 三模式介紹 + 熱搜 chip（若有資料）。
  2. 登入後同一 `/` 看到問候語 hero + 個人額度條 + 節目卡。
  3. 點節目卡 → 未登入預設索引 tab、登入預設對話 tab。
  4. 對話 tab 在未登入時顯示 Lock card variant=anonymous，文案逐字符合定版。
  5. 額度耗盡時顯示 Lock card variant=quota_exhausted，點 CTA 開既有 QuotaApplyModal。
  6. 對話送出後 24 小時內，`SELECT count(*) FROM events WHERE event_type='search_executed'` 增加。
  7. 同一 query 在 7 天內被 3+ 不同 session 送出後，`GET /trending-queries` 回傳含該 query。
  8. 在 QueryPage 點播放，切到 TranscriptPage 不斷音；速度按鈕切換立即反映。
  9. TranscriptPage 與對話 SourceCard 的段落切點一致（同一個 transcript 對比）。
  10. 語意搜尋結果同 episode 多 chunk 時，顯示 `+N 同集` chip 且點開可展開。

- 後端單元測試：`backend/tests/test_trending_queries.py`（cutoff 邊界、days 範圍、空結果）、`backend/tests/test_events_search_executed.py`（payload validation）。

### Scope boundaries

**In scope**：
- 上述 8 個 new capabilities + 2 個 modified capabilities 的前端 + 必要 backend（trending API + events extension）。
- Lock card 兩態（anonymous / quota exhausted）。
- 索引 tab 的 placeholder UI（純佔位，無 retrieval）。
- 熱搜 chip 完整鏈路（emit + query + render）。
- Sticky audio player 跨 QueryPage / TranscriptPage。
- Paragraph 聚合 util 與 TranscriptPage / SourceCard 接線。

**Out of scope**：
- 索引 mode backend retrieval、CTE SQL、結果頁 V-Z 渲染、兩色高亮（→ change `keyword-index-mode`）。
- Disabled user 申訴流程（→ change `disabled-user-appeal-flow`）。
- 後台任何頁面、quota 自動補額 cron、付費升級流程。
- RAG retrieval 演算法 / RRF 排序邏輯本身。
- 修改 `quota_requests` 表 schema 或 `POST /quota-requests` 行為。

## Risks / Trade-offs

- **[風險] HomePage 合併後首屏內容變多 → LCP 變差** → Mitigation：節目卡 lazy-render（IntersectionObserver），hero 與三模式介紹優先 paint；後續用 chrome-devtools-mcp 做 LCP 量測。
- **[風險] Sticky audio player mount 在 router 外，初次載入有空白 audio bar** → Mitigation：未啟用前回傳 `display: none`，只在 `currentEpisodeId !== null` 時才顯示。
- **[風險] 熱搜 chip 早期資料稀疏（cutoff ≥ 3 難達標）** → Mitigation：cutoff 設定為環境變數可調；初期可降到 2 觀察一週後恢復。
- **[風險] Lock card 文案改版需要 user education** → Mitigation：在 release log 寫使用者視角的「為什麼改」。
- **[風險] Paragraph aggregation client-side 跑長逐字稿（>1 小時）效能** → Mitigation：純函式 + O(n) 掃描；TranscriptPage 已 virtualized 渲染，aggregation 算一次 cache 在 state。
- **[Trade-off] 索引 tab 是 placeholder** → 短期讓 user 看到「即將推出」可能有期待落空，但比起延後整個 redesign 等 backend 是較佳選擇；release log 明確標 phase 2。
- **[Trade-off] 不寫具體額度重置時間** → 使用者可能困惑何時恢復，但因無自動補額 cron，寫了會更誤導；用「申請更多次數」CTA 引導正確期望。

