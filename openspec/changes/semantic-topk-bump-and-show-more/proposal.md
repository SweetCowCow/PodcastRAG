## Summary

語意搜尋過撈 k=25，前端以「初始顯示 10 + 顯示更多每次 +5」漸進呈現，取代目前固定回 8 筆且一次全部渲染的行為。

## Motivation

語意模式目前固定顯示 8 筆，源自前端 search 呼叫沒帶 `k`、走 `PublicSearchRequest.k` 的 default 8；但該 endpoint 其實已支援 `k` 1–50。使用者希望看到更多相關片段。語意檢索是 pgvector 向量搜尋、成本極低（唯一 LLM 成本是 query embedding 一次、與 k 無關），所以過撈更多筆數幾乎不增加金錢成本。但有兩個限制要照顧：(1) `SemanticResultList` 目前沒有顯示上限、會把回傳結果一次全部渲染；(2) 後端 enrich 流程對每個 hit 做循序 SQL（前後段、highlight、摘要），延遲隨 k 線性成長。因此需要在「給使用者更多深度」與「不一次傾倒整面卡片 + 不讓初始回應過慢」之間取得平衡。

## Proposed Solution

1. 前端語意 search 呼叫對 `POST /shows/{id}/search` 帶 `k: 25`，一次過撈（不動後端）。
2. `SemanticResultList` 加顯示層上限：初始只渲染前 10 個（依集分組的）lead group，提供「顯示更多」按鈕每按一次 client-side 多顯示 5 個 group，全部顯示完後按鈕消失。沿用 unified-segment-citation-card 既有的 client-slice 漸進顯示做法，但本 change 使用語意專屬常數（初始 10、增量 5）。
3. 漸進顯示一律是對「已過撈的 25 筆」做 client-side slice，不重打 API。

## Non-Goals

- 不修改 search endpoint 契約、retrieval 排序邏輯、或後端 enrich 流程。
- 不做依問題類型動態調整 k（YAGNI，無證據顯示不同問題需要不同深度）。
- 不做後端分頁 / offset。
- 不動索引（keyword）與對話（chat）模式的顯示行為。

## Alternatives Considered

- 分頁重查（每次「顯示更多」打一次 API）：否決——search endpoint 沒有 offset 參數、且每次呼叫都會重新 embed 問題並從頭回傳同一批 top-k，既浪費又拿不到下一頁。
- k 直接設 50（API 上限）：否決——後端 enrich 是 O(k) 循序 SQL，k 越大初始回應越慢；25 在深度與延遲間取得平衡。
- 靜態調大 k 但不加顯示上限：否決——`SemanticResultList` 目前無顯示上限，會一次傾倒 25 張卡片，行動裝置體驗差。

## Impact

- Affected specs: `semantic-mode-result-ui`（modified：新增「過撈深度與顯示上限 + 顯示更多」需求）
- Affected code:
  - Modified:
    - src/QueryPage.jsx（語意 search 呼叫帶 k=25）
    - src/SemanticResultList.jsx（初始 10 + 顯示更多每次 +5 的 client-side 漸進顯示）
  - New: 無
  - Removed: 無
