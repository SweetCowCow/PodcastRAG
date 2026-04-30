## Summary

PodcastRAG 全站加入兩段斷點 RWD（手機 `<768px` / 桌機 `≥768px`），所有頁面（含 admin 後台）皆完整可在手機操作。

## Motivation

PodcastRAG 目前所有頁面用 React inline style 寫死桌機版型：QueryPage 固定 `panelWidth: 340` + resize handle，AdminPage 表單 `gridTemplateColumns: '1fr 1fr 1fr'` 三欄，Modal `minWidth: 380/420`，QueueTab row 把 episode title + show + 4 個 timestamp + 按鈕全擠成一列，TopNav 與 admin sub-tabs 並排顯示 8+ 個按鈕。手機螢幕（360–414 px）開啟會橫向溢出、按鈕擠在一起，使用者無法在外用手機檢視內容或調整排程。`PodcastRAG.html` 入口 viewport meta 已正確（`width=device-width, initial-scale=1.0`），但元件內部沒有任何 RWD 處理。

`/admin/queue/{id}/position` 後端 API 已支援用目標位置 PATCH，但前端拖曳排序綁 HTML5 native drag-and-drop（`draggable={true}`、`onDragStart`/`onDrop`），手機 Safari/Chrome 觸控行為破裂；需要替代手機操作 UI。

## Proposed Solution

新建跨頁面 capability `frontend-responsive-layout`，由共用 hook `useViewport()` 提供 `isMobile` 旗標，每個 component 內部以 `isMobile ? mobileStyle : desktopStyle` 條件渲染。不引入 CSS class、不引入打包工具、不引入第三方 dnd 函式庫。

具體頁面行為：

- **TopNav**：手機隱藏主導覽 flex bar，改顯示 hamburger icon button；點擊展開 dropdown menu 列出「節目選擇 / 後台管理」+ admin sub-tabs。
- **AdminPage sub-tabs（API 金鑰 / LLM 模型 / RAG 設定 / 轉錄排程 / 轉錄序列 / 外部 API 狀態）**：手機改 `overflow-x: auto` 橫向捲動列。
- **PodcastSelect**：grid 既有 `auto-fill minmax(320px, 1fr)`，手機自然 wrap 成單欄；標題列 `flexWrap: 'wrap'` 已有，僅微調 gap 與字級。
- **QueryPage**：手機改 chat 全寬；集數面板從固定右側 panel 變 overlay drawer（從右側滑入覆蓋），標題列加切換 icon button 開關 drawer；resize handle 隱藏（無拖曳餘地）。
- **TranscriptPage**：既有 `maxWidth: 720`，手機 padding 微調，時間戳記 minWidth 處理避免溢出。
- **AdminPage 表單**：三欄 grid `1fr 1fr 1fr` → 單欄 `1fr`；schedule card metadata 直排堆疊；action button 改換行區。
- **Modal（FormModal / ConfirmModal）**：`minWidth: 380/420` 改 `width: min(95vw, 480)`；`padding` 縮小。
- **QueueTab row**：metadata（title / show / badge / timestamps）直排堆疊；action button 換行；隱藏 HTML5 drag handle 與 `draggable` attribute；pending row 顯示「↑」/「↓」icon button，呼叫 `PATCH /admin/queue/{row_id}/position` 帶 `position: targetIdx`（targetIdx = 當前 idx ± 1，邊界 clamp）。
- **觸控目標**：所有可點擊元素最小 44×44 px。

## Non-Goals

- 不支援 tablet 中間斷點（768 px 直接切桌機 layout）— 後台工具型網站，平板使用低，三段斷點增加 conditional 翻倍。
- 不做 PWA / 安裝到主畫面 / 離線模式。
- 不重構為 CSS class + `@media`：codebase 全 inline style + CDN + Babel Standalone，無 build tool；class 重構工作量翻倍且無新功能收益。
- 不引入 `dnd-kit` / `react-dnd` 等觸控拖曳函式庫：用 ↑↓ 按鈕等價達成排序操作，避免依賴。
- 不調整桌機版型（保持既有寬度、間距、字級）— RWD 只加手機分支，不改 default。
- 不改後端 API、不改 schema、不改 cron 行為。
- 不做 i18n 之外的 a11y 強化（現有 ARIA 不擴大）。

## Alternatives Considered

- **CSS classes + `@media` rules**：拒絕。需要把 `style={{ ... }}` 全改 className 並寫 CSS file，且 CDN-only 模式下 CSS 載入順序與 inline style 優先級會有衝突。
- **第三方 RWD 函式庫（react-responsive、@react-hook/media-query）**：拒絕。CDN UMD 版本不穩定；`useViewport` 自己寫 10 行就好。
- **Mobile-specific routes（`/m/*`）**：拒絕。維護兩套頁面違反 DRY，且 admin 路由已用 `page` state 不是 URL。
- **手機完全 disable drag reorder（顯示「請改用桌機」）**：拒絕。使用者需求是手機完整操作。
- **Tablet 中間斷點（768–1024）**：拒絕。後台使用低、三段 conditional 增加維護成本。

## Impact

- Affected specs:
  - New: `frontend-responsive-layout`
  - Modified: `admin-transcription-queue-ui` (drag→arrow buttons on mobile)
  - Modified: `admin-show-management-ui` (modal width, schedule card stacking)
- Affected code:
  - Modified:
    - src/Shared.jsx (TopNav hamburger, FormModal/ConfirmModal width, new useViewport hook)
    - src/App.jsx (pass isMobile to TopNav)
    - src/PodcastSelect.jsx (header layout)
    - src/QueryPage.jsx (chat full-width + drawer panel + hide resize handle)
    - src/TranscriptPage.jsx (padding/timestamp tweaks)
    - src/AdminPage.jsx (sub-tabs scroll, form 3-col→1-col, schedule card stacking, modal width)
    - src/QueueTab.jsx (row stacking, ↑↓ buttons, hide drag on mobile)
  - New: (none)
  - Removed: (none)
