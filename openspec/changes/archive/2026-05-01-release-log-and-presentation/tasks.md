# Tasks

## 1. Single Source of Truth for Release Data

- [x] 1.1 [Single Source of Truth for Release Data] 建立 `src/releaseLog.jsx`，定義 entry schema `{ date, slug, milestone, tag, title:{zh,en}, summary:{zh,en} }` 並 export 到 window
- [x] 1.2 從 `openspec/changes/archive/` 24 個資料夾的 proposal.md 翻譯白話雙語條目，按里程碑分組（v0.1 RAG MVP / v0.2 排程 / v0.3 平行+Queue UI / v0.4 Mobile+友善錯誤）
- [x] 1.3 寫入 24 筆 entries 至 releaseLog.jsx
- [x] 1.4 與使用者 review 24 筆白話化品質

## 2. Stats Snapshot Constant

- [x] 2.1 [Stats Snapshot Constant] 在 `releaseLog.jsx` export `STATS_AS_OF` / `STATS_CHANGES_COUNT` / `STATS_EPISODES_COUNT` / `STATS_VECTORS_COUNT`
- [x] 2.2 從 prod 撈當日 STATS 數字（changes 寫死 24，episodes / vectors 從 backend 或 zeabur-service-exec psql 撈）填入

## 3. Release Log Page Navigation

- [x] 3.1 [Release Log Page Navigation] 建立 `src/ReleaseLogPage.jsx`，接收 `lang` prop
- [x] 3.2 在 `Shared.jsx` 的 TopNav 加「更新日誌 / Release Log」入口，點擊 setPage('release-log')
- [x] 3.3 在 `App.jsx` 加 `page === 'release-log'` 的 case 渲染 ReleaseLogPage
- [x] 3.4 在 `src/i18n.jsx` 補 release log 用的雙語字串
- [x] 3.5 在 `PodcastRAG.html` 引入 `<script type="text/babel" src="src/releaseLog.jsx">` 與 `src/ReleaseLogPage.jsx`

## 4. Release Log Entry Listing

- [x] 4.1 [Release Log Entry Listing] 實作里程碑分組與逆排序邏輯（milestone DESC，內部 date DESC）
- [x] 4.2 實作 entry 卡片：date + Badge（tag→variant: feature→success / fix→warning / enhancement→default / ui→muted）+ title + summary，全部走 TOKEN

## 5. Hash-Based Presentation Routing

- [x] 5.1 [Hash-Based Presentation Routing] 在 `App.jsx` 加 `useEffect` 監聽 `hashchange`：`#presentation` → setPage('presentation')，empty hash → 回上一頁
- [x] 5.2 在 `App.jsx` 加 `page === 'presentation'` 的 case 渲染 PresentationPage（不顯示 TopNav）
- [x] 5.3 確認 TopNav / 其他頁面**沒有任何**進入 presentation 的按鈕或連結（grep 確認）
- [x] 5.4 Esc 按鍵清空 hash（在 PresentationPage keydown handler 內 `location.hash = ''`）

## 6. Slide Deck Structure

- [x] 6.1 [Slide Deck Structure] 建立 `src/PresentationPage.jsx`，內部 state `slideIndex`（0–12），實作 13 張 slide function 依 index 渲染
- [x] 6.2 Slide 0 封面：標題「PodcastRAG — 一個 Podcast RAG 系統的成長軌跡」
- [x] 6.3 Slide 1 系統介紹：一句話定位 + 主要價值點
- [x] 6.4 Slide 2 架構圖：Frontend / Backend / Worker / Postgres+pgvector / Redis 五個方塊 + 連線
- [x] 6.5 Slides 3–6 里程碑 v0.1–v0.4：filter releaseLog 對應 milestone，列出 date + title + tag badge
- [x] 6.6 Slide 7 數字成長：3 個大數字卡 +「截至 STATS_AS_OF」
- [x] 6.7 Slides 8–10 過程心得 inline 內容（見 Section 7）
- [x] 6.8 Slide 11 接下來：列 4–6 條雜項待辦
- [x] 6.9 Slide 12 結尾：致謝 + 站名
- [x] 6.10 Slide 元件外殼：頁面佔滿視窗、深色背景、底部「{slideIndex + 1} / 13」+ 提示
- [x] 6.11 在 `PodcastRAG.html` 引入 `src/PresentationPage.jsx`

## 7. Case Study Slides Inline Content

- [x] 7.1 [Case Study Slides Inline Content] Slide 8 濃縮 `transcription-queue-discussion.md` 為三行（問題 / 轉折 / 學到的事），以 const 寫死於元件內，不 fetch
- [x] 7.2 Slide 9 同上，取自 `sync-naming-redesign.md`
- [x] 7.3 Slide 10 同上，取自 `local-vs-prod-verification-violation.md`

## 8. Keyboard Navigation

- [x] 8.1 [Keyboard Navigation] PresentationPage 內 `useEffect` 綁 `keydown` handler
- [x] 8.2 ArrowRight / Space → slideIndex++（上限 12，邊界保護）
- [x] 8.3 ArrowLeft → slideIndex--（下限 0，邊界保護）
- [x] 8.4 Escape → 清空 hash 退出

## 9. Presentation is Chinese-Only

- [x] 9.1 [Presentation is Chinese-Only] PresentationPage 元件不接受 lang prop，所有文字直接寫繁中字面量
- [x] 9.2 chrome-devtools 驗證 lang === 'en' 時進入 #presentation 仍顯示中文

## 10. 部署與瀏覽器驗證

- [x] 10.1 commit + push 至 GitHub，等 Zeabur 自動部署 frontend
- [x] 10.2 chrome-devtools-mcp 驗 release log 頁里程碑分組、雙語切換、tag badge 顯色
- [x] 10.3 chrome-devtools-mcp 改 URL 加 `#presentation` 進簡報，驗 13 張 slide、左右鍵 / Space / Esc、邊界
- [x] 10.4 修任何 bug 並 redeploy

## 11. PPTX 生成

- [x] 11.1 用 ToolSearch 查詢 `pptx` / `powerpoint` / `slide` 相關 skill
- [x] 11.2 若找到直接用；找不到則提示使用者從 marketplace 安裝相關 plugin
- [x] 11.3 將 13 張 slide 內容對齊網頁版傳入 skill 產出 `PodcastRAG_presentation.pptx`
- [x] 11.4 在 `.gitignore` 加 `*.pptx` 規則
- [x] 11.5 本機開啟 .pptx 確認版面正常

## 12. 流程記憶

- [x] 12.1 建立 `feedback_release_log_maintenance.md`：每次 `/spectra-archive` 完成後 Claude 主動詢問「要不要補進 release log」並起草 entry
- [x] 12.2 更新 `MEMORY.md` 索引

## 13. 收尾

- [x] 13.1 commit 所有變更
- [x] 13.2 archive 階段更新 `project_pending_changes.md`
