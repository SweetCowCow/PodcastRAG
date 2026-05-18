## Summary

ChatBubble 內 `citations`（chunk-level chips）與 `enumeration_episodes`（episode-level cards）兩區並列導致使用者混淆，改為**主從佈局**：列舉題（enum 非空）→ enum card 為主、chunk evidence 摺疊為輔；內容題（enum 為空）→ 維持既有 chunk chips。

## Motivation

R3.3 上線後 prod 觀察：問「馬世芳上過哪幾集」chat 答案上方先列 2 張 enum card（EP143、EP82），下方又列同樣 EP143、EP82 的 chunk chip（紫色「EP143@00:00」），使用者抓不到兩區差異與點擊行為（card 開整集 / chip 跳秒）。R3.3 follow-up issue #2（memory `project_pending_followups.md`）。

兩種 source 性質根本不同：
- `citations` = chunk-level evidence（秒級精準引用，點擊跳該秒）
- `enumeration_episodes` = episode-level metadata（整集卡，點擊開整集 page）

扁平化合併會丟失點擊行為差異；保留並列又造成重複資訊。需要利用「enum 非空 ⇒ 答案性質是列舉」的語意對應，重構視覺主從關係。

## Proposed Solution

**方案 D — 主從佈局**：

| 答案性質判斷 | 主視覺 | 輔視覺 |
|---|---|---|
| **列舉題**：`enumeration_episodes` 非空（長度 ≥ 1） | 上方 EnumerationSection（episode-level cards，沿用既有設計） | 下方摺疊區「為什麼這幾集被選 (N 個段落 evidence)」**預設收起**；展開後渲染既有 citation chips |
| **內容題**：`enumeration_episodes` 為空或 null | 既有 chunk chips（不動） | 無 |

具體 ChatBubble 改動：
1. 條件渲染：`if (enumerationEpisodes?.length > 0)` 走列舉佈局，否則走原本佈局
2. 列舉佈局新增 `<CitationEvidenceCollapse>` 元件包住既有 citation chips list，含 `<summary>` 「為什麼這幾集被選 (N 個段落)」+ `<details>` 預設 collapsed
3. 列舉佈局移除「上面 EnumerationSection + 下面 citations 並列」的 layout
4. 內容佈局不動（不換 chip、不加 collapse）
5. 觸發 `citation_click` event 在 collapsed 與 expanded 兩種狀態都要正確發送（不因摺疊跳過）

## Non-Goals

- 不改後端 schema、不動 `enumeration_episodes` / `citations` 兩個欄位的計算邏輯
- 不改 SourceCard / EnumerationSection 兩個既有元件的內部渲染
- 不做 enum card 上的「⊃ chunk 也有」visual badge（被淘汰的方案 B）
- 不合併兩個 source list 成單一 list（被淘汰的方案 A）
- 不純粹隱藏 citations（被淘汰的方案 C — 會丟 grounding evidence）
- 不改 query_click / event 追蹤的 schema（只確保事件在新佈局下仍正確觸發）
- 不為列舉題加入新的 SQL / API 變更

## Alternatives Considered

- **方案 A 合併**：單一 list 去重 + 「來自 chunk / metadata」標籤 — 砍掉。理由：性質不同（秒級 vs 整集）擠一起資訊密度太高、點擊行為混亂、實作層要新增 source type discriminator
- **方案 B 視覺指示**：兩區保留 + 「⊃ chunk 也有」badge — 砍掉。理由：overlap badge 是補丁、視覺仍重複、無法解決「兩區並列」的根本疑問
- **方案 C 互斥**：enum 非空就完全隱藏 citations — 砍掉。理由：丟掉「為什麼這集被選」的 grounding evidence；user 無法回查段落
- **方案 D 主從佈局**：✅ 採用。保留兩種 source 各自點擊行為、用展開/收起取代並列

## Impact

- Affected specs: `rag-query`（modify chat response 渲染 contract，不動 endpoint）
- Affected code:
  - Modified:
    - `src/QueryPage.jsx`（ChatBubble 條件渲染 + 列舉佈局重構 + EnumerationSection 引用方式不變）
  - New:
    - `src/CitationEvidenceCollapse.jsx`（新元件，列舉佈局內的 chunk evidence 摺疊容器）
  - Removed: 無
- 既有 css token 沿用 `Shared.jsx` TOKEN，不新增 design token
- 無 DB / migration / API contract 變更
- 無新外部依賴
- Prod 驗證：用三題 sample 跑 — (1)「馬世芳上過哪幾集」(enum 非空 → 列舉佈局) (2)「楊大正在 EP143 講了什麼」(enum 空 → 內容佈局) (3)「歌單」(enum 因 topic-trigger 非空 → 列舉佈局)
