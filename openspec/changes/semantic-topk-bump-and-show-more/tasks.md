## 1. 前端：過撈 k=25

- [x] 1.1 在 `src/QueryPage.jsx` 的語意 search 呼叫，request body 由 `{ question }` 改為 `{ question, k: 25 }`（對應 design D1 與 Requirement「Semantic results over-fetch...」的 `k=25` scenario）。驗證：DevTools network 對語意查詢看 `POST /shows/{id}/search` request body 含 `k: 25`；回傳筆數 > 8（過撈生效）。

## 2. 前端：顯示上限 + 顯示更多

- [x] 2.1 在 `src/SemanticResultList.jsx` 加「依集分組後」的顯示上限：新增顯示數量 state（初始 10），只渲染前 N 個 lead group；當 group 數 > N 時顯示「顯示更多 / Show more」按鈕，點擊 client-side `setN(n => n + 5)`、不重打 API；N ≥ group 總數時按鈕不渲染。對外 props 不變（`results`/`lang`/`onPlaySegment`/`onJumpToTranscript`）。同集 collapse（「+N 同集」）行為與排序維持不變（對應 design D2/D3 與 Requirement 三個 group-cap scenario）。驗證：mock-harness 或 prod smoke —— 14 group → 初始顯示 10 + 顯示更多；點一次 → 顯示 14、無新 `/search` 請求、按鈕消失；6 group → 全顯示無按鈕。

## 3. 收尾

- [ ] 3.1 `spectra validate semantic-topk-bump-and-show-more` exit 0 + 對 `src/QueryPage.jsx` / `src/SemanticResultList.jsx` 跑 babel transform 無 parse error + prod smoke 語意查詢確認：request body `k=25`、初始 10 group、「顯示更多」+5 不重打 API、露完按鈕消失、排序與既有一致、索引/對話模式不受影響。驗證：(a) validate exit 0；(b) babel transform OK；(c) prod smoke 截圖（初始 10 + 顯示更多後）貼 PR。
