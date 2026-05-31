## Summary

把索引／語意／對話三模式各自不同的引用來源呈現，收斂到一個共用的「引用片段卡」葉子元件，並把「播放此段」與「跳到逐字稿」拆成兩個動作，同時讓顯示數量與檢索 top_k 解耦。

## Motivation

目前同樣一段「引用」在三個模式長得完全不一樣，使用者認知負擔高：

- 索引模式用自寫的 `T1ChunkCard`（片段 3 句 + 跳播合一 + 展開上下文 + 兩色高亮）。
- 語意模式與對話內容題用 `SourceCard`（前後文 + 單色紫高亮 + 跳播合一）。
- 對話列舉題用 `EnumerationSection` 的集層級卡，**完全沒有片段、沒有播放**，只有「跳到這集」（t=0）。

三套葉子 + 兩種高亮 + 跳播全是「播放與導航綁一起」的單一按鈕，列舉題還拿不到片段。使用者實際想要的是一致的行為：每個引用都能看到對應逐字稿片段、能單獨試聽該段、能點進逐字稿看上下文。

此外，對話的引用張數直接跟著檢索 `k`（public search 預設 8、可 1–50；chat 走 `RETRIEVAL_TOP_K`）連動，`k` 一拉大畫面就被大量卡片淹沒。

## Proposed Solution

1. **抽共用葉子 `<SegmentCitationCard>`**（放 `src/Shared.jsx`，`SourceCard` 升級或被它取代），三模式都用同一葉子。卡片內容：逐字稿片段文字 + 高亮 + 集標題 + 時間戳 + 兩顆分開的動作鈕。
2. **拆兩顆動作鈕**：`▶ 播放此段`（觸發既有 sticky audio player `playFromTime`，原地播放不離頁）與 `跳到逐字稿`（導航到 TranscriptPage 該片段看上下文）。取代現在 `onSourceJump` 把 playFromTime 與導航綁在一起的單一行為。
3. **容器各模式保留、但收斂成同一種模式**：索引 T1/T3 = 扁平片段 list、索引 T2 = 依集分組展開片段、語意 = 依集分組、對話內容題 = 依集分組。各容器的 leaf 一律換成 `<SegmentCitationCard>`。
4. **列舉題維持「集清單」主結構**，但每張集卡可展開出共用片段卡（複用既有 `GET /episodes/{id}/transcript` fetch + 依 term 過濾的展開機制），讓列舉題也拿得到片段/播放/上下文。
5. **顯示數量與 top_k 解耦**：每段/每組顯示上限約 5，超出以「顯示更多」漸進載入；對話只顯示 LLM 實際引用的 chunk（`cited_hits`，本來就 < k）。
6. **高亮雙模式**：卡片 API 同時支援「傳 `terms[]` → 多詞兩色（橘 #f97316 實線 / 青 #06b6d4 虛線，索引用）」與「傳 server `highlights` HTML → 單色紫（語意/對話用，沿用 `sanitiseMarkOnly`）」。

## Non-Goals

- 不動 RAG 檢索邏輯與 `top_k` 本身（只改前端顯示層；解耦指的是顯示張數，不改檢索取幾筆）。
- 不動 `POST /shows/{id}/keyword-search`、`/search`、`/query` 等後端 endpoint 的契約。
- 不做引導範例問題（placeholder / example chip）——屬並行 change `per-show-mode-example-prompts`（Change B）。
- 不新增 episode-scoped 取相鄰 chunk 的 endpoint（沿用既有 transcript fetch）。

## Alternatives Considered

- **連容器一起統一成單一清單**：否決——索引的 T1/T2/T3 AND 分層語意、對話的依集分組、列舉題的「哪幾集」意圖是真實且不同的結構，硬統一會丟資訊。只統一葉子即可。
- **只用 placeholder 引導 + 不重構卡片**：那是另一回事（Change B），不解決三套葉子不一致的核心問題。
- **保留三套葉子只調樣式對齊**：治標——行為（跳播合一、列舉題無片段）仍不一致，且日後再 drift。

## Impact

- Affected specs:
  - New: `segment-citation-card`（共用片段卡的契約：片段 + 高亮雙模式 + 播放/跳轉兩鈕 + 顯示上限）
  - Modified: `conversation-source-panel`（對話來源面板改用共用卡 + 兩鈕 + 顯示上限）
  - Modified: `semantic-mode-result-ui`（語意結果改用共用卡）
- Affected code:
  - New:
    - `src/SegmentCitationCard.jsx`（新共用葉子元件 + 高亮 helper）
  - Modified:
    - `src/Shared.jsx`（匯出共用卡 / `SourceCard` 升級或轉呼叫）
    - `src/SemanticResultList.jsx`（leaf 換成共用卡）
    - `src/ConversationSourcePanel.jsx`（leaf 換成共用卡 + 顯示上限）
    - `src/KeywordResults.jsx`（`T1ChunkCard`/T3 卡/`T2EpisodeCard` 展開改用共用卡）
    - `src/QueryPage.jsx`（`EnumerationSection` 集卡加展開片段卡；`onSourceJump` 拆成 play 與 jump 兩條 callback）
    - `openspec/LANGUAGE.md`（補 canonical「引用片段卡 / segment-citation-card」+ 界定 citation/source/segment）
  - Removed: 無（`T1ChunkCard` 等併入共用卡，非獨立刪檔）
- 依賴順序：本 change 會改到索引結果 UI（`keyword-search-results-ui`），建議在 `keyword-index-mode` archive（其 spec 進 canonical）之後再 apply，避免改到尚未固化的 spec。
