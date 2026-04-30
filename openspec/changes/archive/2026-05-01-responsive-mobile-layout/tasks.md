## 1. 共用 hook 與全域樣式

> Spec：`frontend-responsive-layout` → `Frontend exposes a responsive viewport hook`
> Design：`useViewport hook 的實作位置與行為`、`斷點選擇：兩段 768 px`

- [x] 1.1 實作 design 決定「useViewport hook 的實作位置與行為」：在 `src/Shared.jsx` 新增 `useViewport` hook，初值用 `window.innerWidth < 768` 同步取得（避免首 render flicker），`useEffect` 內掛 `resize` listener 用 `requestAnimationFrame` throttle，unmount 時 cleanup
- [x] 1.2 在 `src/Shared.jsx` 檔尾 `Object.assign(window, {...})` 匯出 `useViewport`
- [x] 1.3 對齊 spec requirement「Frontend exposes a responsive viewport hook」— 確認 5 個 scenarios（mobile init / desktop init / resize cross / same-band no extra render / cleanup）皆對應實作

## 2. TopNav 手機 hamburger menu

> Spec：`frontend-responsive-layout` → `Top navigation collapses to hamburger menu on mobile`
> Design：`TopNav 手機版改 hamburger menu`

- [x] 2.1 在 `src/Shared.jsx` 的 `TopNav` 元件呼叫 `useViewport()` 取 `isMobile`
- [x] 2.2 `isMobile === true` 時隱藏既有 nav `<flex>` bar，改顯示一顆 ☰ icon button（`Icon name="menu"` 若無則加新 icon）
- [x] 2.3 用 `useState` 控制 dropdown 開合 `[menuOpen, setMenuOpen]`，hamburger button onClick 切換；dropdown 用 absolute position 覆蓋從上方滑下
- [x] 2.4 dropdown 內列出主 nav items（節目選擇 / 後台管理）+ 語言切換按鈕，每項點擊後呼叫 `setMenuOpen(false)`
- [x] 2.5 `isMobile === false` 時 TopNav 渲染回今日的桌機 flex bar（無 hamburger）
- [x] 2.6 確認 `Shared.jsx` 是否有 `menu` icon；若無，在 `Icon` 元件 SVG 字典裡新增三條橫線 path
- [x] 2.7 對齊 spec requirement「Top navigation collapses to hamburger menu on mobile」— 5 個 scenarios（hamburger 出現 / 桌機 bar 出現 / dropdown list / 點擊收起 / sub-tabs 橫向捲動）走完

## 3. AdminPage sub-tabs 橫向捲動

> Spec：`frontend-responsive-layout` → `Top navigation collapses to hamburger menu on mobile`（同 requirement 末段）
> Design：`TopNav 手機版改 hamburger menu`（最後一段）

- [x] 3.1 在 `src/AdminPage.jsx` 找到 admin sub-tabs 容器（API 金鑰 / LLM / RAG / 排程 / 序列 / API 狀態 6 顆 tab 的 flex 列），呼叫 `useViewport()`
- [x] 3.2 `isMobile === true` 時容器加 `overflow-x: auto`、`flexWrap: 'nowrap'`、`whiteSpace: 'nowrap'`，每個 tab button 加 `flexShrink: 0`
- [x] 3.3 確認桌機 viewport sub-tabs 樣式不變（`isMobile === false` 走原樣式）

## 4. Modal 寬度 viewport-aware

> Spec：`frontend-responsive-layout` → `Form modals adapt width to viewport`
> Design：`Modal 寬度從固定 minWidth 改 viewport-aware`

- [x] 4.1 實作 design 決定「Modal 寬度從固定 minWidth 改 viewport-aware」：在 `src/Shared.jsx` 的 `FormModal` inner box style 把 `minWidth: 380, maxWidth: 480` 改 `width: 'min(95vw, 480px)'`，`maxWidth` 移除（避免 conflict）
- [x] 4.2 `ConfirmModal` inner box style 同樣改 `width: 'min(95vw, 520px)'`
- [x] 4.3 inner box 加 `useViewport()`，`isMobile === true` 時 padding 改 `'18px 18px'`，否則維持 `'22px 26px'`
- [x] 4.4 對齊 spec requirement「Form modals adapt width to viewport」— 兩個 scenarios（360px fit、1280 px 維持 480）走完

## 5. 觸控目標 ≥ 44×44 px

> Spec：`frontend-responsive-layout` → `Touch targets meet 44 px minimum on mobile`
> Design：（含於各 component 改動內）

- [x] 5.1 在 `Shared.jsx` 的 `Btn` size="sm"、`OverflowMenu` 觸發按鈕、`TopNavItem` 加 `useViewport`，`isMobile === true` 時 `min-height: 44, min-width: 44, padding: '11px 14px'`（保留視覺 icon 大小不變，僅擴大 hit area）
- [x] 5.2 `Icon` 包成可點擊的元素時（如 OverflowMenu 觸發鈕、ConfirmModal 關閉鈕、TopNav hamburger）以 `padding` 擴展滿足 44 px
- [x] 5.3 `AdminPage.jsx` Schedule modal 內 day_of_week segmented button 在 mobile 加 `min-height: 44, min-width: 44`（既有 `minWidth: 44` 已有，補 `min-height`）
- [x] 5.4 `QueueTab.jsx` row 內所有 Btn 在 mobile 加 `min-height: 44`
- [x] 5.5 對齊 spec requirement「Touch targets meet 44 px minimum on mobile」— 兩個 scenarios（mobile 擴展 / 桌機不變）走完

## 6. PodcastSelect 手機版微調

> 文件無單獨 spec requirement（grid auto-wrap 已合規），design 涵蓋

- [x] 6.1 在 `src/PodcastSelect.jsx` 呼叫 `useViewport()`，`isMobile === true` 時頂部標題列（line ~51）`gap` 從 16 縮 12，搜尋框 `width: 280` 改 `width: '100%'`
- [x] 6.2 確認 grid `gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))'` 在 360 px 寬會自然變單欄（minmax 320 > 360-padding 觸發單欄）

## 7. QueryPage 手機版 chat 全寬 + 集數 drawer

> Spec：`frontend-responsive-layout` → `Query page replaces split panel with overlay drawer on mobile`
> Design：`QueryPage 手機版：chat 全寬 + 集數 drawer`

- [x] 7.1 在 `src/QueryPage.jsx` 元件內呼叫 `useViewport()`、加 state `[drawerOpen, setDrawerOpen]`
- [x] 7.2 `isMobile === true` 時主版 layout 改：chat region `flex: 1` 占 100% 寬，集數面板（line ~67）改 `position: 'fixed', right: 0, top: 0, bottom: 0, width: 'min(85vw, 360px)', transform: drawerOpen ? 'translateX(0)' : 'translateX(100%)', transition: 'transform 0.18s ease-out', zIndex: 100`
- [x] 7.3 在 chat region 頂部標題列加一顆 drawer toggle icon button（`Icon name="list"` 或 menu icon），onClick `setDrawerOpen(true)`
- [x] 7.4 drawer 開啟時加全屏 overlay `<div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 99 }} onClick={() => setDrawerOpen(false)} />`
- [x] 7.5 `isMobile === true` 時 resize handle（line ~57）不渲染
- [x] 7.6 `isMobile === false` 時保留桌機 split layout（chat + 340 panel + resize handle）原樣
- [x] 7.7 對齊 spec requirement「Query page replaces split panel with overlay drawer on mobile」— 4 個 scenarios（drawer 預設關閉 / toggle 滑入 / overlay 點擊關閉 / 桌機不變）走完

## 8. TranscriptPage 手機版微調

> 文件無單獨 spec requirement，design 涵蓋

- [x] 8.1 在 `src/TranscriptPage.jsx` 呼叫 `useViewport()`，`isMobile === true` 時主容器 `padding` 從 desktop 預設縮為 `'12px 14px'`
- [x] 8.2 line 158 timestamp `<div style={{ minWidth: 80 }}>` 在 mobile 縮 `minWidth: 60` + `fontSize: 11`，避免時間戳擠壓內容

## 9. AdminPage 表單三欄 → 單欄

> Spec：`frontend-responsive-layout` → `Form grid layouts collapse to single column on mobile`
> Design：`AdminPage 表單三欄 grid → 單欄`

- [x] 9.1 在 `src/AdminPage.jsx` 元件內呼叫 `useViewport()`
- [x] 9.2 line ~836 `gridTemplateColumns: '1fr 1fr 1fr'`（schedule 建立表單）在 mobile 改 `'1fr'`、`gap` 從 14 縮 12
- [x] 9.3 `isMobile === false` 時 grid 維持 `'1fr 1fr 1fr'` 不變
- [x] 9.4 對齊 spec requirement「Form grid layouts collapse to single column on mobile」— 兩個 scenarios（mobile 直排 / 桌機橫排）走完

## 10. AdminPage Schedule modal 手機版

> Spec：`admin-show-management-ui` → `Schedule modal renders mobile-friendly layout`
> Design：（沿用 Modal 寬度 + 三欄→單欄）

- [x] 10.1 在 `src/AdminPage.jsx` schedule edit modal 內部用 `useViewport()`；modal 寬度改動由 `FormModal` 共用元件處理（任務 4 已完成）
- [x] 10.2 modal 內若有任何 `gridTemplateColumns: '1fr 1fr'` 或 `'1fr 1fr 1fr'` 在 mobile 改 `'1fr'`
- [x] 10.3 day_of_week segmented button group 各按鈕 `min-height: 44` 在 mobile 加上（既有 `minWidth: 44` 已有）
- [x] 10.4 對齊 spec requirement「Schedule modal renders mobile-friendly layout」— 4 個 scenarios（modal fits 360 / 三欄堆疊 / day picker 觸控 / 桌機不變）走完

## 11. AdminPage Schedule cards 手機版直排

> Spec：`admin-show-management-ui` → `Schedule cards stack vertically on mobile`
> Design：（沿用 schedule card layout）

- [x] 11.1 在 `src/AdminPage.jsx` schedule list 卡片渲染處（line ~964 `<div key={item.show_id}>`）用 `useViewport()`
- [x] 11.2 `isMobile === true` 時卡片內最外層 `flex` row 改 `flexDirection: 'column'`、`gap: 12`
- [x] 11.3 `isMobile === true` 時 action button 區（查看進度 / 立刻執行轉錄 / 更多操作）從 `flexShrink: 0` 改 `flexWrap: 'wrap'`
- [x] 11.4 `isMobile === true` 時卡片 `padding` 從 `'18px 22px'` 改 `'14px 16px'`
- [x] 11.5 metadata 行 `flexWrap: 'wrap'` 已有，無需動
- [x] 11.6 `isMobile === false` 時卡片渲染原樣
- [x] 11.7 對齊 spec requirement「Schedule cards stack vertically on mobile」— 3 個 scenarios（卡片堆疊 / 按鈕 wrap / 桌機不變）走完

## 12. QueueTab row 手機版 + ↑↓ 重排按鈕

> Spec：`admin-transcription-queue-ui` → `Admin page exposes a Transcription Queue tab`、`Pending row reorder uses arrow buttons on mobile`
> Design：`拖曳排序在手機版的替代：每個 pending row 加 ↑ / ↓ icon button`、`QueueTab row 手機版直排`

- [x] 12.1 在 `src/QueueTab.jsx` `Row` 元件內呼叫 `useViewport()`
- [x] 12.2 `isMobile === true` 時 row 主容器 `display: flex; gap: 12; alignItems: 'flex-start'` 改 `flexDirection: 'column'`，`gap: 8`
- [x] 12.3 `isMobile === true` 時隱藏左側 drag handle（`⋮⋮` span，line 255）；移除 `draggable` attribute、`onDragStart` / `onDragEnd` handler 綁定條件加 `&& !isMobile`
- [x] 12.4 `isMobile === true` 時 action button 區改 `flexWrap: 'wrap'`
- [x] 12.5 在 `Section` 元件 title 顯示處：`status === 'pending' && isMobile` 時 title 改去掉「（可拖動排序）」/「(drag to reorder)」字尾，改「排隊中」/「Pending」
- [x] 12.6 實作 design 決定「拖曳排序在手機版的替代：每個 pending row 加 ↑ / ↓ icon button」：在 `Row` action button 區，`isPending && isMobile` 時於既有「取消」按鈕前加兩顆 `Btn size="sm" variant="ghost" icon="chevronUp"` / `chevronDown`，`disabled` 條件由父元件傳入 `canMoveUp` / `canMoveDown`
- [x] 12.7 `Section` 把 pending rows 的索引 i 與 length n 傳給 `Row`，row 計算 `canMoveUp = i > 0 && !dragInFlight`、`canMoveDown = i < n - 1 && !dragInFlight`
- [x] 12.8 新增 handler `moveRow(row, direction)`：取得當前 pendingDisplay 中該 row 的 index `i`，target row 為 `pendingDisplay[i + (direction === 'up' ? -1 : 1)]`，呼叫 `PATCH /admin/queue/{row.id}/position` body `{position: target.position}`；成功後 `setPendingOverride(null)` + `refetch()`，失敗 `setActionErr(row.id, ...)`，過程中 `setDragInFlight(true)`
- [x] 12.9 `isMobile === false` 時 ↑↓ 按鈕不渲染、drag handle 與 draggable 維持原樣
- [x] 12.10 確認 `chevronUp` / `chevronDown` icon 在 `Shared.jsx` `Icon` 字典裡有；若無則新增
- [x] 12.11 對齊 spec requirement「Pending row reorder uses arrow buttons on mobile」— 6 個 scenarios（首列 ↑ disable / 末列 ↓ disable / ↑ swap / 進行中 disable 全部 / 失敗顯示 error / 桌機不變）走完
- [x] 12.12 對齊 spec requirement「Admin page exposes a Transcription Queue tab」— mobile 行為（row 直排、無 drag handle、pending 標題簡化）走完

## 13. 部署與驗證

- [x] 13.1 commit + push 到 main 觸發 Zeabur 部署；前端為 static plan，build 後等 `https://podcastrag.zeabur.app/src/Shared.jsx` 內容含 `useViewport` 字串確認部署完成
- [x] 13.2 用 chrome-devtools-mcp `resize_page` 模擬 iPhone 14 Pro（393×852）走過：節目選擇 → 進入查詢頁 → 開 drawer → 看逐字稿 → 後台登入 → 切到排程 → 開 modal 改頻率到 weekly 點 day picker → 切到佇列 → 切三 sub-tab → 點 pending row ↑↓ 排序至少 1 次成功
- [x] 13.3 用 chrome-devtools-mcp 模擬 iPhone SE（375×667）跑同樣流程，確認 modal、drawer、按鈕觸控目標皆未破版
- [x] 13.4 桌機 viewport（1280×800）回歸測試：所有頁面與 modal 樣式與今日相同（regression check）
- [x] 13.5 iPad mini 直立（768×1024）邊界測試：確認顯示桌機 layout（≥ 768 → desktop）；若實機顯示擠則回 design open question 評估調整斷點
