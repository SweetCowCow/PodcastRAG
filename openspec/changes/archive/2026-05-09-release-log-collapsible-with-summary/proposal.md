## Summary

把 ReleaseLogPage 每筆 entry 預設收合（accordion），點擊標題列展開內容；標題列除原有版本/日期/標題外，新增「重點摘要」以 2-4 個列點呈現，幫助使用者一眼掃描更新內容。

## Motivation

目前 ReleaseLogPage 一次把所有 entry 全文展開，到 v1.4 entry 已多達 10+ 筆，使用者要捲動很久才看完，也不易快速判斷哪些版本與自己相關。改成預設收合 + 重點摘要，可同時兼顧瀏覽速度與細節可達性。

## Proposed Solution

- ReleaseLogPage 每筆 entry 拆成「標題列（永遠可見）」+「內容區（可折疊）」兩段。
- 標題列保留原本的版本號、日期、entry 標題，並新增 2-4 個 bullets 的重點摘要。
- 內容區預設 `collapsed`，點擊標題列任何位置切換展開／收合；展開時旁邊的 chevron 圖示同步轉向。
- 新增的「重點摘要」資料來源：直接寫進 `RELEASE_ENTRIES` 結構，作為新欄位 `summaryBullets`（zh / en 雙語），不從 body 自動抽取。
- 鍵盤可用：標題列為 `<button>` 元素，可 Tab focus、Enter / Space 切換。
- 預設狀態為全部收合，但 URL hash（例如 `#v1-4`）可指向某筆 entry 自動展開並 scroll into view，沿用既有 anchor 行為。

## Non-Goals

- 不做「展開／收合全部」的全域按鈕（保持頁面簡潔；未來再說）。
- 不做 entry 搜尋或 tag 篩選。
- 不做「使用者展開狀態 persist 到 localStorage」。
- 不做 RELEASE_ENTRIES 資料結構大改造（僅新增 `summaryBullets` 一個 optional 欄位，沒填的 entry 退化成只顯示標題列）。
- 不對舊 entry 一次補齊摘要 — 由 user 之後逐筆補；本 change 只負責 UI + schema + 一筆 v1.4 範例。

## Alternatives Considered

- **自動從 body 抽前 3 行當摘要**：放棄。body 結構不一致（有 H3 / 列表 / 段落），抽出來常常不是重點，反而誤導。
- **預設展開最新一筆，其餘收合**：放棄。增加判斷 + 跟 URL hash 行為衝突；保持「全部收合 + hash 指向自動展開」更可預期。

## Impact

- Affected specs: 1 個 modified（release-log-ui）。
- Affected code:
  - Modified: src/ReleaseLogPage.jsx（accordion 行為 + summaryBullets 渲染 + RELEASE_ENTRIES schema 新增 zh/en 欄位 + 為 v1.4 entry 補一筆範例摘要）
