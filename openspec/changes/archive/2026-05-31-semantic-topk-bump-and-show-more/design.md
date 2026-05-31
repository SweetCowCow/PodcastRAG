## Context

語意模式（`QueryPage` 的 semantic tab）目前固定顯示 8 筆結果：前端語意 search 呼叫只送 `{ question }`、沒帶 `k`，後端 `PublicSearchRequest.k` 預設 8（範圍 1–50）。`SemanticResultList` 收到結果後依集分組（lead + 「+N 同集」collapse），且沒有任何顯示上限——回幾筆就渲染幾筆。

兩個既有事實限制本設計：

- search endpoint 沒有 offset / 分頁；每次呼叫都重新 embed 問題並從頭回傳 top-k。所以「顯示更多」不能靠重打 API，必須一次過撈、前端漸進顯示。
- 後端 enrich 流程對每個 hit 做 3 次循序 SQL（前後段、ts_headline highlight、ai_summary）；無 per-hit LLM。所以過撈不增加金錢成本，但初始回應延遲隨 k 線性成長。

## Goals / Non-Goals

**Goals**
- 語意結果可看到比 8 筆更多的相關片段。
- 不一次傾倒整面卡片：初始顯示有上限，其餘漸進揭露。
- 零後端改動、不動排序。

**Non-Goals**
- 不改 search endpoint 契約、retrieval 排序、enrich 流程。
- 不做依問題類型動態 k。
- 不做後端分頁 / offset。
- 不動索引、對話模式顯示。

## Decisions

### D1：過撈 k=25（前端帶 k，後端不動）

語意 search 呼叫對 `POST /shows/{id}/search` 帶 `k: 25`。一次過撈 25 筆。選 25 不選 50：enrich 是 O(k) 循序 SQL，k 越大初始回應越慢；25 在「給足漸進深度」與「壓住 enrich 延遲」間平衡。25 在 endpoint 允許的 1–50 範圍內。

### D2：顯示層上限 + 顯示更多（client-side slice）

`SemanticResultList` 對「依集分組後的 group 清單」做顯示上限：初始渲染前 10 個 group，提供「顯示更多」按鈕每按 client-side 多顯示 5 個 group，全部顯示完按鈕消失。所有漸進顯示都是對已過撈的 25 筆做 client-side slice，不重打 API。常數為語意專屬：初始 10、增量 5。

### D3：上限作用在「集分組」層級而非單卡

`SemanticResultList` 既有行為是先依 episode 分組（同集多 chunk collapse 成 lead + 「+N 同集」chip）。顯示上限套在 group 數（顯示前 N 個 lead group），與既有分組/collapse 行為相容；「+N 同集」展開仍是各 group 內部行為、不受顯示上限影響。

## Implementation Contract

**Observable behavior**
- 語意查詢送出時，對 search endpoint 帶 `k=25`（DevTools network 可見 request body `k:25`）。
- 結果初始最多顯示 10 個（依集分組的）lead group；當分組數 > 10 時出現「顯示更多」。
- 點「顯示更多」每次多顯示 5 個 group、不重新呼叫 API、不重整頁面；顯示完全部後按鈕消失。
- 排序與既有完全一致（只是顯示更多既有結果），「+N 同集」collapse 行為不變。

**Interface**
- 前端語意 search 呼叫的 request body 由 `{ question }` 改為 `{ question, k: 25 }`。
- `SemanticResultList` 內部新增顯示數量 state（初始 10、增量 5）與「顯示更多」控制；對外 props 不變（仍接 `results` / `lang` / `onPlaySegment` / `onJumpToTranscript`）。

**Failure modes**
- 過撈回傳少於 10 個 group（含 0）：全部顯示、不出現「顯示更多」、無錯誤。
- search 失敗（既有錯誤路徑）：沿用既有錯誤顯示，不受本 change 影響。

**Acceptance criteria**
- prod smoke：語意查詢的 `/search` request body `k=25`；結果初始顯示 10 個 group + 「顯示更多」；點一次 +5、不重打 API（network 無新 `/search` 請求）；露完後按鈕消失。
- 同一查詢的結果排序與本 change 前一致（ranking 未動）。
- 索引、對話模式顯示不受影響。

**Scope boundaries**
- **In scope**：`src/QueryPage.jsx` 語意 search 帶 k=25；`src/SemanticResultList.jsx` 初始 10 + 顯示更多 +5 client-slice。
- **Out of scope**：後端 endpoint / 排序 / enrich、動態 k、後端分頁、索引/對話模式。

## Risks / Trade-offs

- [過撈 25 筆讓初始 /search 變慢] → enrich 是 O(k) 循序 SQL；k=25 相對 k=8 約 3x enrich 次數，預估增加數百毫秒。接受此延遲換更多深度；若日後變痛，follow-up 可平行化 enrich（需處理 asyncpg 單 session 不可並發查詢，屬後端改動，YAGNI）。
- [顯示上限藏掉相關結果] → 「顯示更多」可達全部 25 筆既有上限；排序不變、不會藏掉高排名結果。
- [行動裝置一次太多卡] → 初始 10 個 group 上限正是為此；漸進 +5 controlled。
