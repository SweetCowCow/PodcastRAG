## 1. 共用葉子元件

- [x] 1.1 新增 `src/SegmentCitationCard.jsx`，匯出 `SegmentCitationCard`（props 見 design D1）：渲染片段文字 + 集標題 + 時間戳 + AI 摘要(可展開)，並在檔末 `Object.assign(window, { SegmentCitationCard, highlightTerms })`。在 `index.html` `<script type="text/babel">` 於 `Shared.jsx` 之後、消費者（`SemanticResultList`/`QueryPage`/`KeywordResults`）之前載入（對應 Requirement「Unified segment citation card across modes」）。驗證：本機 mock-harness 以 mock segment 渲染，瀏覽器看到片段文字 + 集標題 + 時間戳；babel transform 無 parse error。

- [x] 1.2 在 `SegmentCitationCard` 實作雙模式高亮（對應 design D2 與 Requirement「Dual-mode term highlighting」）：傳 `terms[]` 非空 → 沿用 `highlightTerms` 兩色（even 橘 `#f97316` 實線 / odd 青 `#06b6d4` 虛線）；否則傳 `segment.highlights` HTML → `sanitiseMarkOnly` 後單色紫 `<mark>`；否則純文字。驗證：mock-harness 兩組輸入（給 `terms` vs 給 `highlights`）各渲染，devtools 檢查 `<mark>` computed style：兩色組 even 橘實線/odd 青虛線、單色組 accent 紫。

- [x] 1.3 在 `SegmentCitationCard` 實作播放/跳轉兩顆鈕（對應 design D3 與 Requirement「Separate play and jump-to-transcript actions」）：`▶ 播放此段` 呼叫 `onPlay(segment)`、`跳到逐字稿` 呼叫 `onJumpToTranscript(segment)`；`segment.audio_url` 缺或無 `onPlay` 時隱藏播放鈕；`segment.source === 'description'` 時隱藏播放鈕且跳轉鈕 label 改「打開該集 / Open episode」。驗證：mock-harness 三情境（有 audio_url、無 audio_url、description）各確認鈕的顯示/隱藏與 label，點播放不觸發導航 callback、點跳轉只觸發 jump callback。

## 2. Shared.jsx 相容層

- [x] 2.1 在 `src/Shared.jsx` 把 `SourceCard` 改為轉呼叫 `SegmentCitationCard`（把既有 `source`/`onJump`/`position` 映射到新 props，`onJump` 暫時同時接 play+jump 以維持舊 caller 不爆），或保留為 thin wrapper（對應 Requirement「Unified segment citation card across modes」末句）。驗證：既有匯出 `Object.assign(window,{... SourceCard ...})` 仍存在；mock-harness 用舊 `SourceCard` props 渲染不報錯。

## 3. QueryPage callback 拆分

- [x] 3.1 在 `src/QueryPage.jsx` 把現有 `onSourceJump`（先 `audio.playFromTime` 再導航）拆成兩條 callback（design D3）：`onPlaySegment(segment)` 只呼叫 `audio.playFromTime(episode_id, start_time, { title, audio_url })` 不導航；`onJumpToTranscript(segment, position?, queryId?)` 觸發 citation_click beacon + `onOpenEpisode({id,title}, start_time)` 導航。兩條都傳入各容器（對應 Requirement「Separate play and jump-to-transcript actions」）。驗證：prod smoke — 對話/語意/索引任一卡，點播放 sticky player 開始播且頁面不跳、點跳轉導航到 TranscriptPage 對應秒數。

## 4. 各容器 leaf 換卡 + 顯示上限

- [x] 4.1 `src/SemanticResultList.jsx`：把 `SourceCard` 葉子換成 `SegmentCitationCard`（design D4；傳 server `highlights` 走單色、傳 relevance prop 畫相關度條），保留「+K 同集」collapse 行為（實作 spec Requirement「Semantic results render as flat top-K list...」與「Each Semantic SourceCard shows a relevance bar...」）。驗證：prod smoke 語意查詢 — 卡片為共用卡、相關度條在、同集 chip 展開正常、單色高亮。

- [x] 4.2 `src/ConversationSourcePanel.jsx`：把 `SourceCard` 葉子換成 `SegmentCitationCard`（design D4），並對每個 episode group 加顯示上限（design D6 的 `CITATION_DISPLAY_CAP=5`）+「顯示更多」client slice（對應 Requirement「Chat tab renders a single episode-grouped source panel」與「Displayed citation count decoupled from retrieval top_k」）。驗證：prod smoke 對話內容題 — 依集分組、每組 ≤5 張 + 顯示更多可增量、卡片有播放/跳轉兩鈕。

- [x] 4.3 `src/KeywordResults.jsx`：把 `T1ChunkCard`、T3 精簡卡、T2 展開查看各段的 leaf 都換成 `SegmentCitationCard`（design D4）（傳 `terms` 走兩色高亮、傳 `onPlay`/`onJumpToTranscript`）；移除/併入原 `T1ChunkCard` 自寫渲染（對應 Requirement「Unified segment citation card across modes」）。驗證：prod smoke 索引查詢 — T1/T3 片段卡、T2 展開段，皆為共用卡且兩色高亮、播放/跳轉兩鈕。

## 5. 列舉題展開片段卡

- [x] 5.1 `src/QueryPage.jsx` 的 `EnumerationSection`：每張集卡加「展開查看各段」toggle（design D5），複用既有 `GET /episodes/{id}/transcript` fetch + 依該列舉關鍵詞/topic terms 過濾 segments，inline 渲染 `SegmentCitationCard` list（不離頁）；保留集清單主結構與「跳到這集」（對應 Requirement「Enumeration episodes expand to inline segment cards」）。驗證：prod smoke 列舉題（如「歌單 哪幾集」）— 集清單在，展開某集 inline 出現片段卡含播放/跳轉，0 段時顯示「（此集無可顯示的命中段落）」placeholder。

## 6. 詞彙與收尾

- [x] 6.1 在 `openspec/LANGUAGE.md` 補 canonical entry：`引用片段卡 / SegmentCitationCard`，並界定 `citation`（被答案引用的片段）/ `source`（檢索命中的片段）/ `segment`（逐字稿片段）三者差異與 `avoid` 同義詞（對應 proposal Vocabulary）。驗證：`LANGUAGE.md` 出現新 entry 含 definition/avoid/why。

- [ ] 6.2 跑 `spectra validate unified-segment-citation-card` + babel transform 全部改動 JSX 無 parse error + 對 prod 三模式（索引/語意/對話含列舉題）做手動 smoke（截圖貼 PR）。驗證：(a) `spectra validate` exit 0；(b) `node` babel transform 改動的 `.jsx` 全 OK；(c) 三模式 smoke 確認共用卡 + 兩色/單色高亮 + 播放/跳轉兩鈕 + 顯示上限 + 列舉展開皆正確。
