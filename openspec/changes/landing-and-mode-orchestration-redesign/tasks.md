## 1. Backend：events 表 search_executed 擴展

- [ ] 1.1 擴展 `POST /events` 接受 `event_type="search_executed"`，payload schema 為 `{show_id: UUID, query_text: 1-500 chars, mode: "semantic" | "chat"}`，未知 event_type 或不合法 payload 回 422；以新增的 `backend/tests/test_events_search_executed.py` 含 4 個案例（happy path、unknown mode、overlong query_text、missing key）跑綠驗證 events ingestion endpoint accepts citation_click payloads 仍含 citation_click 行為。
- [ ] 1.2 確認 `POST /events` 對 `search_executed` 仍套用既有 per-IP rate limit 60/min 不變，session cookie 解析 user_id 邏輯不變；以擴充 `backend/tests/test_events_api.py` 加一個「authenticated user emit search_executed」案例斷言 row 含 user_id 跑綠驗證。

## 2. Backend：trending-queries endpoint

- [ ] 2.1 新增 `backend/app/api/trending_queries.py` 提供 `GET /shows/{show_id}/trending-queries`，依 design 決策 4 的 SQL（events GROUP BY payload->>'query_text' HAVING count>=cutoff ORDER BY count DESC LIMIT 10）回傳 `{queries, days, cutoff}`；以新增 `backend/tests/test_trending_queries.py` 內 happy path 案例（5 / 3 / 1 次三 query → 回前兩個）跑綠驗證 GET trending-queries endpoint returns popular query strings per show。
- [ ] 2.2 trending-queries endpoint 對未知 show 回 404、空結果回 200 with `queries: []`、days 超出 1-30 回 422；以 `test_trending_queries.py` 三個邊界案例跑綠驗證。
- [ ] 2.3 trending-queries 的 cutoff 從環境變數讀取，預設 3；以 `test_trending_queries.py` 加一個 monkeypatch cutoff=2 的案例斷言行為改變跑綠驗證。
- [ ] 2.4 trending-queries 套用與 `POST /events` 相同的 per-IP rate limit 60/min；以 `test_trending_queries.py` 連送 61 次第 61 次回 429 跑綠驗證。

## 3. Frontend：基礎元件骨架

- [x] 3.1 新增 `src/HomePage.jsx` 元件骨架（hero 區、mode trio 區、show grid 區三個 section），auth state 從 `AuthContext` 取得，未 resolved 前顯示 loading；以 chrome-devtools-mcp 開首頁手動驗證 HomePage replaces LandingPage and PodcastSelect at site root 行為符合（兩種狀態 hero swap + 無 flash）。
- [x] 3.2 在 `src/App.jsx` 將 `/` 路由由 `LandingPage` / `PodcastSelect` 二擇一改為一律渲染 `HomePage`；同時刪除 `src/LandingPage.jsx`、`src/PodcastSelect.jsx`，並在 `PodcastRAG.html` 移除舊兩檔的 `<script>` 引用；以 `git grep "LandingPage\|PodcastSelect"` 應只剩 release log 等歷史紀錄，瀏覽器開 `/` 仍正常驗證。
- [x] 3.3 新增 `src/ModeTrioIntro.jsx` 並在 `HomePage` 中段渲染三張非可點教育卡（索引 / 語意 / 對話），各含描述 + 1 固定範例 + 額度標，行動端（width<768px）垂直 stack；以 chrome-devtools-mcp 1280px 與 375px 兩斷點截圖驗證 HomePage shows mode trio education section。
- [x] 3.4 在 `HomePage` 中實作 hero 兩變體：未登入呈現 marketing headline + Google 登入 CTA（呼叫既有 `LoginModal`）；已登入呈現個人化問候 + 剩餘對話額度，無 Google 登入按鈕；以瀏覽器登入 / 登出兩態手動斷言文案差異驗證 HomePage hero CTA differs by auth state。
- [x] 3.5 在 `HomePage` 渲染 show grid，沿用既有 `<ShowCard>`（從 PodcastSelect 抽出搬入 `Shared.jsx` 或 `HomePage.jsx`），呼叫 `GET /shows` 與卡片資料規格與既有相同；以 chrome-devtools-mcp 抓 prod show 數驗證 HomePage renders show grid with real backend data。

## 4. Frontend：QueryPage 三 tab 編排

- [x] 4.1 在 `src/QueryPage.jsx` 頂部新增 `<ModeTabs>` 三 tab strip（索引 / 語意 / 對話），順序與 auth state 無關固定不變；以瀏覽器登入 / 登出兩態 DOM 檢查驗證 QueryPage exposes three mode tabs。
- [x] 4.2 QueryPage 初次 mount 後依 `/me` 結果決定 active tab：登入 → 對話、未登入 → 索引；中途登入不自動切 tab；以手動操作（未登入打開 → 確認 Index → 點 LoginModal 登入 → 確認 tab 不變）驗證 Default tab is decided by authentication state。
- [x] 4.3 QueryPage 將輸入字串提升為跨 tab 共用 controlled state、每個 mode 維護獨立 result bucket；切 tab 不清空輸入、回到舊 tab 不重打 API；以 chrome-devtools-mcp 的 network panel 確認切回前一 tab 無新 request 驗證 Switching tabs preserves input string and per-mode results。
- [x] 4.4 索引 tab 渲染「即將推出」placeholder，含切到語意、切到對話兩個入口元素；輸入任何字串 + Enter 不發任何 retrieval request、不 emit `search_executed`；以 network panel 與 placeholder 文字驗證 Index tab renders placeholder pending backend implementation。

## 5. Frontend：Lock card 兩態

- [x] 5.1 新增 `src/LockCard.jsx` 接 `variant: 'anonymous' | 'quota_exhausted'` prop；對話 tab 在未登入或 `quota.remaining===0` 時用 LockCard 完全覆蓋答案區，輸入框與 tab strip 仍可操作；以未登入 + 額度=0 兩態手動驗證 LockCard covers Chat tab answer area for two states，並以 Semantic / Index tab 驗證該 tab 不出現 LockCard。
- [x] 5.2 `anonymous` 變體渲染逐字符合 design.md 的定版 zh / en 文案（🔒 / 不想花時間重聽找答案？/ 登入後... / 以 Google 登入 / 或先用語意搜尋找找看相關片段），主 CTA 呼叫既有 `LoginModal`、副連結切到 Semantic tab；以瀏覽器斷言文案無「免費」「數字額度」「重置時間」字串驗證 Anonymous LockCard renders exact bilingual copy and login CTA。
- [x] 5.3 `quota_exhausted` 變體渲染逐字符合 design.md 的定版 zh / en 文案（⏳ / 已達使用上限 / 如果還需要... / 申請更多次數 / 或先用語意搜尋找找看相關片段），主 CTA 開既有 `QuotaApplyModal`（接 `POST /quota-requests` 不改 schema）、副連結切到 Semantic tab；以瀏覽器斷言文案無「每月」「每週」「重置」「重新計算」「自動恢復」字串驗證 Quota-exhausted LockCard renders exact bilingual copy and apply CTA。
- [x] 5.4 將 LockCard 的 zh / en 文案加進 `src/i18n.jsx`，並補上 LockCard test ids 方便 chrome-devtools-mcp 操作；以切語言切換手動驗證兩種 variant 在 en 下文案語意對齊。

## 6. Frontend：對話 source panel 整併

- [x] 6.1 新增 `src/ConversationSourcePanel.jsx`，輸入 citations 後按 `episode_id` 分組，episode 標題只顯示一次，組內列出該集 SourceCards，組標題可點擊收合 / 展開；以一筆含 4 citations 跨 2 episodes 的答案手動驗證 Chat tab renders a single episode-grouped source panel。
- [x] 6.2 ConversationSourcePanel 頂部固定渲染標頭 `答案參考來源（共 N 集 · M 段引用）`（zh）/ `Answer sources (N episodes · M citations)`（en），N 為 unique episode 數、M 為 total chunk 數；以表格範例（2 episodes / 5 chunks → 共 2 集 · 5 段引用）瀏覽器斷言驗證 Source panel header reports unique-episode and total-chunk counts。
- [x] 6.3 替換 QueryPage 對話 tab 既有 chip + card 雙區為單一 `<ConversationSourcePanel>`，移除 chip 列相關 markup；以 chrome-devtools-mcp DOM 檢查確認沒有重複 episode chip 列驗證。

## 7. Frontend：Paragraph aggregation util

- [x] 7.1 新增 `src/utils/aggregateParagraphs.js` 純函式，input segments + opts，依 design 決策 7 規則切段（gap ≥ 1.5s 或 speaker 變化），output paragraphs；以新增 `src/utils/aggregateParagraphs.test.js`（如無 test runner 則改用 manual smoke script）覆蓋表格邊界（gap 1.0 / 1.5 / 2.0、speaker change、empty input）驗證 aggregateParagraphs util produces paragraphs by silence gap and speaker change。
- [x] 7.2 改寫 `src/TranscriptPage.jsx` 與對話 / 語意的 SourceCard 渲染邏輯，全部改用 `aggregateParagraphs`，移除任一處既有 inline merge / 分段邏輯；以同一個 transcript 對比 TranscriptPage 與 SourceCard 段落數一致手動驗證 TranscriptPage and SourceCard share the same paragraph aggregation 與 Source panel uses shared paragraph aggregation for chunk text。

## 8. Frontend：Sticky audio player

- [x] 8.1 新增 `src/StickyAudioPlayer.jsx`，內含單一 `<audio>` element + 速度切換 UI；掛在 `App.jsx` router 外層、提供 React Context `AudioPlayerContext` 暴露 `playFromTime/pause/seek/setSpeed` 與 `currentEpisodeId/currentTime/isPlaying/speed`；以 chrome-devtools-mcp 操作播放後切頁，DOM 中 `<audio>` element 始終同一個 instance 驗證 StickyAudioPlayer mounts once outside the page router。
- [x] 8.2 QueryPage 與 TranscriptPage 內所有「在這段播放」按鈕改為呼叫 `AudioPlayerContext.playFromTime(episodeId, startSec)`，移除頁面自有 `<audio>`；以 QueryPage 點播放 → 切 TranscriptPage 同集音訊不中斷且 currentTime 單調遞增手動驗證 AudioPlayerContext exposes a stable control interface。
- [x] 8.3 StickyAudioPlayer 速度控制只開 1.0x / 1.25x / 1.5x 三檔，循環切換，並以 `localStorage.audio_speed` 持久化、reload 後恢復；以瀏覽器手動點切換 → reload → 再播放速度仍維持驗證 Playback speed is restricted to three discrete values and persisted。

## 9. Frontend：熱搜 chip 串接

- [x] 9.1 新增 `src/TrendingQueriesChips.jsx`，呼叫 `GET /shows/{id}/trending-queries?days=7` 取結果，最多渲染 5 個 chip（count 降序）；空結果 / 失敗時靜默不渲染且無錯誤訊息；以 prod 有資料 show 與空資料 show 兩態驗證 Chips render in count-descending order, limited to five 與 Empty endpoint response hides chip section silently。
- [x] 9.2 TrendingQueriesChips 嵌入 HomePage 的每張 ShowCard 與 QueryPage 的 Semantic / Chat tab 上方；以 DOM 檢查兩處皆呈現驗證 HomePage and QueryPage call trending-queries and render chips。
- [x] 9.3 點 chip 立即把 chip 文字塞入 QueryPage 輸入框、依當前 active mode 自動送出 query；以手動點 Chat tab 上的 chip 觀察 chat endpoint 被呼叫、Semantic tab 上同一 chip 觀察 semantic endpoint 被呼叫驗證 Clicking a chip submits the query in active mode。

## 10. Frontend：search_executed event emit

- [x] 10.1 在 QueryPage 的 Semantic 與 Chat 成功回應 handler 內以 `navigator.sendBeacon`（fallback fetch keepalive）`POST /events` 寫 `{event_type: "search_executed", payload: {show_id, query_text, mode}}`；失敗 swallow、不顯任何 UI error；以 chrome-devtools-mcp network panel 抓送出的 events 請求驗證 QueryPage emits search_executed event after successful semantic or chat query。
- [x] 10.2 在查詢失敗（5xx / network error）路徑斷言「不 emit search_executed」、Index tab placeholder 路徑斷言「不 emit search_executed」；以兩個手動操作（觸發 500 + Index tab 輸入）觀察 network panel 無 events 請求驗證 Failed query does not emit search_executed 與 Index tab does not emit search_executed。

## 11. Frontend：語意 mode hybrid C 渲染

- [x] 11.1 新增 `src/SemanticResultList.jsx`，依 RRF 順序渲染 flat list，同 episode 多 chunk 時只渲染最高分一筆並掛 `+{N} 同集` chip；以一個能命中同集多 chunk 的 query 手動驗證 Semantic results render as flat top-K list with same-episode collapse。
- [x] 11.2 SemanticResultList 的 chip 點擊展開該集剩餘 chunks（依原 ranked 順序緊接卡片下方），chip 改成「收合」狀態或消失；以點 chip 前後 DOM 數量驗證 Clicking the chip expands collapsed chunks 與 Single chunk per episode renders no chip。
- [x] 11.3 每張 Semantic SourceCard 右側渲染相關度 bar，按 normalized rank 線性 100%→10%，不顯任何 RRF 數字文字；以 chrome-devtools-mcp DOM 檢查斷言頁內無 score 浮點數文字驗證 Each Semantic SourceCard shows a relevance bar without raw score。
- [x] 11.4 將 QueryPage 的 Semantic tab 改為渲染 `<SemanticResultList>` 取代既有 list；以前後對比手動驗證原本同集重複的雜訊消失。

## 12. 整合 + 移除舊路徑驗證（涵蓋 landing-page REMOVED Requirements 遷移）

- [x] 12.1 刪除 `src/LandingPage.jsx` 與 `src/PodcastSelect.jsx`，並在 release log（`src/releaseLog.jsx`）加一條使用者視角的 changelog；以 `git status` 確認兩檔被刪、瀏覽器開所有路徑無 404 / console error 驗證 landing-page capability 的 REMOVED Requirements 已遷移（包含 Landing Page renders for unauthenticated visitors at site root、Landing Page hero presents copy and primary CTA、Landing Page lists collected shows with real data、Landing Page paywall band explains the freemium boundary and offers login、Landing Page top navigation includes secondary login button 五條的退場）。
- [ ] 12.2 全頁面回歸 smoke：未登入 / 登入兩態，各跑 HomePage → 點 ShowCard → QueryPage（三 tab 切換）→ 點 SourceCard 進 TranscriptPage → 切回 QueryPage 音訊不斷；以 chrome-devtools-mcp 全流程錄一輪 console message 無 error 驗證跨 capability 整合無 regression。
- [ ] 12.3 部署至 Zeabur 後對 prod 跑同一輪 smoke，並以 prod DB 連線 `SELECT count(*) FROM events WHERE event_type='search_executed' AND created_at > now() - interval '10 minutes'` > 0 驗證 emit 鏈路在 prod 真的寫入。

## 13. 設計決策回掃（對應 design.md ### headings）

- [x] 13.1 走查任務 3.1-3.5、12.1 的實作，確認符合「決策 1：HomePage 合併 LandingPage 與 PodcastSelect」的單一元件 + hero swap + LandingPage / PodcastSelect 退場決定；以 design.md 對照 code review 通過驗證。
- [x] 13.2 走查任務 4.1-4.4 的實作，確認符合「決策 2：QueryPage 改三 tab、預設 tab 視登入狀態」的 tab strip + 預設 tab + 字串保留 + 索引 placeholder；以 design.md 對照 code review 通過驗證。
- [x] 13.3 走查任務 5.1-5.4 的實作，確認符合「決策 3：Lock card 兩態 + 接既有 QuotaApplyModal」的兩 variant + 接 QuotaApplyModal + 不寫額度數字 / 重置時間；以 design.md 對照 code review 通過驗證。
- [x] 13.4 走查任務 1.1-2.4、9.1-10.2 的實作，確認符合「決策 4：熱搜 chip 走既有 events 表」的 events 擴展 + trending-queries endpoint + chip 串接；以 design.md 對照 code review 通過驗證。
- [x] 13.5 走查任務 6.1-6.3 的實作，確認符合「決策 5：對話 source panel 整併為 episode-grouped」的單一 panel + 標頭 + 取消 chip 列；以 design.md 對照 code review 通過驗證。
- [x] 13.6 走查任務 8.1-8.3 的實作，確認符合「決策 6：Sticky audio player 跨頁共用 single instance」的 router 外掛載 + context + 速度持久化；以 design.md 對照 code review 通過驗證。
- [x] 13.7 走查任務 7.1-7.2 的實作，確認符合「決策 7：Paragraph aggregation client-side + 共用 util」的純函式 + 共用消費；以 design.md 對照 code review 通過驗證。
- [x] 13.8 走查任務 11.1-11.4 的實作，確認符合「決策 8：語意 mode 採 hybrid C 渲染（flat list + 同集 chip + 相關度 bar）」的三項視覺契約；以 design.md 對照 code review 通過驗證。
- [x] 13.9 走查任務 3.3 的實作，確認符合「決策 9：Mode trio 介紹區不可點 + 1 固定範例」的不可點 + 行動端 stack + 1 範例；以 design.md 對照 code review 通過驗證。
- [x] 13.10 對照 design.md Implementation Contract 的 Behavior / Interfaces / Data shape / Failure modes / Acceptance criteria / Scope boundaries 全部小節，逐項勾選任務 1-12 已覆蓋；以 design.md 對照清單 walkthrough 通過驗證。
