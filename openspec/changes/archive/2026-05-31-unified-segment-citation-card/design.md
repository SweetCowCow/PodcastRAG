## Context

PodcastRAG 三個查詢模式各自渲染引用來源，葉子元件與行為都不同：

- 索引（`src/KeywordResults.jsx`）：`T1ChunkCard`（3 句預覽 + 展開上下文 + 「跳播」+ 兩色高亮）、T2 集卡（展開查看各段）、T3 精簡卡。
- 語意（`src/SemanticResultList.jsx`）→ `SourceCard`（`src/Shared.jsx`）：前後文 + 單色紫 server `<mark>` + 跳播。
- 對話內容題（`src/ConversationSourcePanel.jsx`）→ `SourceCard`：依集分組。
- 對話列舉題（`src/QueryPage.jsx` 的 `EnumerationSection`）：集層級卡，無片段、無播放，只有「跳到這集」（t=0）。

兩個既有事實限制本設計：

- `onSourceJump`（`QueryPage.jsx`）目前先 `audio.playFromTime(...)` 再 `onOpenEpisode(...)` 導航——播放與導航綁在同一個動作。
- 對話引用張數來自 `cited_hits`（LLM 實際引用的 chunk），語意/索引則顯示到檢索 cap；`k` 預設 8、可 1–50。

## Goals / Non-Goals

**Goals**
- 三模式共用同一個引用片段葉子元件，外觀與行為一致。
- 每張卡可「單獨播放該片段（不離頁）」與「跳到逐字稿該片段看上下文」兩個獨立動作。
- 列舉題在保留「集清單」主結構下，也能展開出片段卡。
- 顯示張數與檢索 `k` 解耦（顯示層 cap + 顯示更多）。

**Non-Goals**
- 不改檢索邏輯 / `top_k` 取幾筆 / 後端 endpoint 契約。
- 不做引導範例問題（Change B）。
- 不新增取相鄰 chunk 的 endpoint。

## Decisions

### D1：共用葉子 `<SegmentCitationCard>`（新檔 `src/SegmentCitationCard.jsx`）

統一卡片，props：

```
<SegmentCitationCard
  segment={{ episode_id, episode_title, start_time, end_time, text,
             before_text?, after_text?, highlights?, ai_summary_excerpt?,
             ai_summary_full?, source?, audio_url? }}
  terms={string[]?}     // 有值 → 多詞兩色高亮
  position={number?}    // 序號 badge（語意/對話用）
  lang
  onPlay={(segment)=>void}             // 播放此段；缺則不顯示播放鈕
  onJumpToTranscript={(segment)=>void} // 跳到逐字稿
/>
```

`src/Shared.jsx` 既有 `SourceCard` 改為轉呼叫 `SegmentCitationCard`（或直接被取代並更新 `Object.assign(window,...)` 匯出），維持既有 caller 不爆。

### D2：高亮雙模式（取代現在兩套）

卡片內決定高亮來源，優先序：
1. `terms` 非空 → 對 `segment.text` 跑 client 端多詞兩色高亮（even idx 橘 `#f97316` 實線、odd idx 青 `#06b6d4` 虛線；沿用 `KeywordResults.highlightTerms` 的規則）。
2. 否則 `segment.highlights`（server `ts_headline` HTML）非空 → `sanitiseMarkOnly` 後單色紫渲染（沿用既有 `.source-card mark` 樣式）。
3. 否則純 `segment.text`。

### D3：播放與跳轉拆兩顆鈕（取代 `onSourceJump` 綁一起）

- `▶ 播放此段`：呼叫 `onPlay(segment)`；`QueryPage` 接到 `audio.playFromTime(episode_id, start_time, { title, audio_url })`，**不導航**。`segment.audio_url` 缺（或 `audio` hook 不存在）時隱藏播放鈕。
- `跳到逐字稿`：呼叫 `onJumpToTranscript(segment)`；`QueryPage` 接到既有 `onOpenEpisode({id, title}, start_time)` 導航 TranscriptPage。`source==='description'`（`start_time` 無意義）時 label 改「打開該集」、不顯示播放鈕。
- `QueryPage` 把現在的單一 `onSourceJump` 拆成 `onPlaySegment` 與 `onJumpToTranscript` 兩條 callback 傳入各容器；citation_click beacon 在 `onJumpToTranscript` 路徑觸發（維持既有埋點）。

### D4：容器保留、leaf 一律換成共用卡

| 容器 | 結構 | leaf |
|------|------|------|
| 索引 T1 / T3（`KeywordResults`） | 扁平片段 list | `SegmentCitationCard`（T1 給 `terms`、T3 給 `terms`） |
| 索引 T2（`KeywordResults`） | 依集分組，展開查看各段 | 展開內容 = `SegmentCitationCard` list |
| 語意（`SemanticResultList`） | 依集分組（lead + 「+K 同集」） | `SegmentCitationCard`（給 server `highlights`） |
| 對話內容題（`ConversationSourcePanel`） | 依集分組可收合 | `SegmentCitationCard`（給 server `highlights`） |
| 對話列舉題（`EnumerationSection`） | 集清單（主） | 集卡展開 → `SegmentCitationCard` list |

### D5：列舉題集卡可展開片段卡

`EnumerationSection` 每張集卡加「展開查看各段」toggle，複用 `KeywordResults` T2 已用的 `GET /episodes/{id}/transcript` fetch + 依該列舉的關鍵詞/topic terms 過濾 segments，inline 渲染 `SegmentCitationCard` list，不離頁。集清單主結構與「跳到這集」維持。

### D6：顯示張數與 top_k 解耦

- 顯示層常數 `CITATION_DISPLAY_CAP = 5`：語意/對話每組、索引每段，預設只渲染前 5 張，其餘以「顯示更多」漸進（語意/對話用 client slice 既有資料；索引沿用既有 offset 分頁）。
- 對話引用維持只顯示 `cited_hits`（< k），不額外抓未被引用的 chunk。
- 不改任何後端取幾筆。

## Implementation Contract

**Observable behavior**
- 三模式中每一張引用卡的版面、高亮、按鈕都來自同一個 `SegmentCitationCard`。
- 每張卡（非 description-source）同時有「播放此段」與「跳到逐字稿」兩顆鈕；點播放只在 sticky player 播放、頁面不跳走；點跳轉才導航到 TranscriptPage 對應 `start_time`。
- 列舉題集卡展開後，下方 inline 出現該集片段卡（含播放/跳轉），頁面不離開。
- 任何分組/段落初始最多顯示 5 張卡，超出顯示「顯示更多」；點擊後增量出現，不重整頁面。
- 索引模式多詞查詢的卡片以兩色高亮；語意/對話卡片以單色紫高亮。

**Interface**
- 新增 `window.SegmentCitationCard`（props 見 D1）+ `window.highlightTerms`（沿用既有）。
- `Shared.jsx` 的 `SourceCard` 對既有 caller 保持可呼叫（轉呼叫或保留 thin wrapper）。
- `QueryPage` 對外多兩條 callback：`onPlaySegment(segment)`、`onJumpToTranscript(segment, position?, queryId?)`。

**Failure modes**
- `segment.audio_url` 缺或無 audio hook → 隱藏播放鈕，只留跳轉鈕。
- `source==='description'`（`start_time` 不可靠）→ 不顯示播放鈕、跳轉鈕 label 改「打開該集」。
- 列舉題展開 fetch 失敗 / 0 段 → 顯示「（此集無可顯示的命中段落）」，不報錯、不離頁。
- `terms` 與 `highlights` 都缺 → 顯示純片段文字。

**Acceptance criteria**
- `src/SegmentCitationCard.jsx` 可在 mock harness 以 (a) 給 `terms` 與 (b) 給 server `highlights` 兩種輸入渲染，兩色 / 單色高亮各自正確（devtools 檢查 `<mark>` computed style）。
- 三模式（索引 T1/T2/T3、語意、對話內容題、對話列舉題展開）在 prod 都渲染同一張卡；播放鈕原地播、跳轉鈕導航至正確 `start_time`。
- 任一段/組超過 5 筆時「顯示更多」出現並可增量載入；對話引用張數等於 `cited_hits` 數量、不隨額外 chunk 膨脹。
- `pytest` 不受影響（純前端 change，無後端契約改動）；`spectra validate` exit 0。

**Scope boundaries**
- **In scope**：`SegmentCitationCard` 新元件、`SourceCard` 升級、`SemanticResultList`/`ConversationSourcePanel`/`KeywordResults`/`EnumerationSection` leaf 換卡、`QueryPage` callback 拆分、顯示 cap、`LANGUAGE.md` 詞彙。
- **Out of scope**：RAG 檢索 / top_k 取幾筆、後端 endpoint、引導範例問題（Change B）、新增相鄰 chunk endpoint。

## Risks / Trade-offs

- [SourceCard 轉呼叫破壞既有 caller] → 保留 `SourceCard` 為 thin wrapper、prod smoke 三模式都驗。
- [兩色高亮對色盲] → 沿用既有實線/虛線下劃線雙重區隔，不純靠色彩。
- [顯示 cap 藏掉相關結果] → 「顯示更多」可達既有上限；對話本來就只顯示 cited。
- [列舉題展開 fetch 整集 segments 量大] → 依關鍵詞過濾後才渲染，且只在使用者主動展開時抓。
- [依賴 `keyword-index-mode` 尚未 archive] → 建議該 change archive 後再 apply 本 change，避免改到尚未進 canonical 的 `keyword-search-results-ui` spec。
