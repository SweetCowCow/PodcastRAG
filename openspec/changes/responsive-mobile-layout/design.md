## Context

PodcastRAG 走 CDN + Babel Standalone 模式（`index.html` 直接載 React 18 UMD + Babel transform `.jsx`），無打包、無 CSS preprocessor、無 build step。所有 component 在 `src/*.jsx` 內用 React inline style（`style={{ ... }}`）寫死視覺，design token 集中在 `src/Shared.jsx` 的 `TOKEN`。`PodcastRAG.html`（實際檔名 `index.html`）的 viewport meta 已正確設置。

固定寬度與多欄版型散落各處：
- `src/QueryPage.jsx:25` `panelWidth: 340` 固定 + resize handle
- `src/AdminPage.jsx:836` 表單 `gridTemplateColumns: '1fr 1fr 1fr'` 三欄
- `src/AdminPage.jsx` schedule modal：`src/Shared.jsx:200,219` FormModal `minWidth: 380/420`
- `src/QueueTab.jsx:236` HTML5 native drag (`draggable={isPending}`, `onDragStart` / `onDrop`)
- `src/Shared.jsx:142` TopNav `display: 'flex'`，admin sub-tabs 同樣 flex，皆無 wrap/scroll

`/admin/queue/{row_id}/position` 後端 API 接受 `{position: int}` payload；前端目前只在拖曳放下時呼叫，無「上移／下移」UI 入口。

## Goals / Non-Goals

**Goals**：

- 提供共用 `useViewport()` hook：監聽 `window.innerWidth`，回傳 `{ isMobile }`（`< 768` 為 true）。
- 每個 component 內以 `isMobile ? mobileStyle : desktopStyle` 條件渲染，桌機 layout 完全不變。
- 手機版（< 768px）所有頁面（含 admin）皆可完整操作：閱讀、查詢、編輯排程、管理佇列。
- 隱藏 HTML5 drag-and-drop UI 在手機版；以「↑」/「↓」icon button 取代 pending row 排序操作，呼叫既有 `PATCH /admin/queue/{row_id}/position` API。
- 所有可點擊元素手機版最小觸控目標 44×44 px。

**Non-Goals**：

- 不支援 tablet 中間斷點（768–1024）— 直接以 `< 768` 為手機、`>= 768` 為桌機。
- 不引入 CSS class 或 `@media` rule、不引入打包工具、不引入第三方 dnd 函式庫。
- 不改桌機版型（fixed widths、grid columns、modal sizes 在 `>= 768` 維持原樣）。
- 不改後端 API、不改 DB schema。
- 不做 PWA、安裝、離線。
- 不擴大 a11y / ARIA（現有保持）。

## Decisions

### 斷點選擇：兩段 768 px

**選擇**：`isMobile = window.innerWidth < 768`，`>= 768` 視為桌機。

**理由**：iPhone Pro Max 寬度 430 px、iPhone 標準 390–414、小螢幕 360；iPad mini 直立 768；iPad 11" 直立 834。768 為業界標準斷點且與 iPad 直立邊界對齊。後台工具型網站，平板使用低；三段斷點會讓每個 component 多一倍 conditional 與測試成本。

**Alternatives considered**：三段（< 768 mobile / 768–1024 tablet / ≥ 1024 desktop）— 拒絕，平板使用低、ROI 不對等；640 / 1024 雙斷點（Tailwind sm/lg）— 拒絕，640 偏小（iPhone Pro Max 直立會被當「桌機」）。

### `useViewport` hook 的實作位置與行為

**選擇**：在 `src/Shared.jsx` 新增 `useViewport`，初值由 `window.innerWidth` 同步取得（避免首 render 閃爍），`useEffect` 內掛 `resize` listener 更新 state；unmount 時移除 listener。Throttle 以 `requestAnimationFrame` 包裝 — 同一 frame 多次 resize 只觸發一次 setState。

**理由**：放 `Shared.jsx` 與 `TOKEN` 同檔便於匯出，呼叫端無需 import path 心智成本（既有模式 `Object.assign(window, {...})` 公開）。`requestAnimationFrame` 比 `setTimeout` debounce 更貼合 layout 改動節奏。

**Alternatives considered**：`window.matchMedia('(max-width: 767px)')` + `addEventListener('change')` — 同樣可行，但兩種事件監聽程式碼風格相異；統一用 `resize` event。

### 拖曳排序在手機版的替代：每個 pending row 加 `↑` / `↓` icon button

**選擇**：手機版 pending row 隱藏 `draggable` 與 `onDragStart` / `onDrop` handler、隱藏左側 `⋮⋮` drag handle 圖示；改在 row 右側 action 區於既有「取消」按鈕前加兩顆 `Btn size="sm" variant="ghost"`，內容為 `Icon name="chevronUp" / chevronDown" size={14}`。第一筆 row 的 `↑` disabled、最後一筆的 `↓` disabled。點擊送 `PATCH /admin/queue/{row_id}/position` body `{position: targetPosition}`，targetPosition 為當前 row 的 `position` ± 1（pending 列表 ordered by position asc，目前 `pendingDisplay[i].position`）。

**理由**：等價達成桌機拖曳功能；後端 API 已支援；無新依賴、無觸控事件處理；按鈕尺寸滿足 44×44 觸控目標。

**Alternatives considered**：`react-dnd` / `dnd-kit` UMD CDN — 拒絕，套件體積大且 CDN 版本不一定穩；`pointerdown` + `pointermove` 自製 long-press drag — 拒絕，需處理 scroll vs drag 衝突，工作量遠大於兩顆按鈕。

### TopNav 手機版改 hamburger menu

**選擇**：TopNav 偵測 `isMobile` 時，主導覽 flex bar 收摺為一顆 `☰` icon button（左上）；點擊展開絕對定位 dropdown（從上方滑下覆蓋），列表項：「節目選擇 / 後台管理」+ 語言切換按鈕；點擊任一項目後關閉 dropdown。Admin sub-tabs（API 金鑰 / LLM / RAG / 排程 / 佇列 / API 狀態）不放進 hamburger，仍保留在頁面內、改 `overflow-x: auto + flex` 橫向捲動列。

**理由**：admin sub-tabs 6 個塞 hamburger 會讓兩層 menu 點擊路徑長；橫向捲動是後台慣例（GitHub mobile、Slack 都用）。主 nav 只 2 項放 hamburger 簡單、清爽。

**Alternatives considered**：bottom tab bar — 拒絕，admin sub-tabs 6 個塞不下；admin sub-tabs 收 hamburger — 拒絕，多一層點擊。

### Modal 寬度從固定 `minWidth` 改 viewport-aware

**選擇**：`FormModal` 的 inner box style `minWidth: 380, maxWidth: 480` 改為 `width: min(95vw, 480)`；`ConfirmModal` 的 `minWidth: 420, maxWidth: 520` 改 `width: min(95vw, 520)`。`padding: '22px 26px'` 在手機版改 `'18px 18px'`。`OverflowMenu` dropdown `minWidth: 180` 不動（內容短）。

**理由**：`min(95vw, 480)` 桌機等同原 maxWidth、手機自動縮到 95% 視窗寬，避免 overflow。Padding 縮小避免內容區擠壓。

**Alternatives considered**：手機版改全螢幕 modal — 拒絕，schedule edit modal 內容短，全螢幕反而視覺浪費。

### QueryPage 手機版：chat 全寬 + 集數 drawer

**選擇**：手機版主版 `flex: 1` chat 占 100% 寬，集數面板從 `width: 340` 固定 panel 改為 fixed-position drawer（`position: fixed; right: 0; top: 0; bottom: 0; width: min(85vw, 360); transform: translateX(100%)` 預設收起），點擊頂部新加的「集」icon button 切換 `transform: translateX(0)` 滑入。Resize handle 完全不渲染（手機無拖曳餘地）。Drawer 開啟時頁面背後加 `rgba(0,0,0,0.5)` overlay 點擊關閉。

**理由**：360 px 螢幕扣掉 340 px panel 只剩 20 px 給 chat 不可用；drawer 是手機 panel 標準模式。

**Alternatives considered**：bottom sheet（從下方滑上）— 拒絕，集數列表通常較長，bottom sheet 高度受限；上方 dropdown — 拒絕，按鈕在頂部會擋 chat 標題列。

### AdminPage 表單三欄 grid → 單欄

**選擇**：`src/AdminPage.jsx` 中所有 `gridTemplateColumns: '1fr 1fr 1fr'` 在手機版改 `'1fr'`，`gap` 從 14 縮 12。Schedule edit modal 內欄位本來就 `flexDirection: column`，僅微調 input padding 與 button 寬度。

**理由**：手機 360 px 寬度三欄每格 ~100 px，input/select 的 padding 加上 label 會擠成醜；單欄是手機表單慣例。

### QueueTab row 手機版直排

**選擇**：手機版 `Row` 主容器從 `display: flex; gap: 12; alignItems: 'flex-start'` 改 `flexDirection: 'column'`；左側 drag handle `⋮⋮` 隱藏（手機版無 drag）；標題列 `flexWrap: 'wrap'` 已有；timestamps `flexWrap` 已有；action button 區 `flex-shrink: 0` 改 `flex-wrap: wrap` 可換行；所有 button `min-height: 44`、`padding: '10px 12px'`。

**理由**：360 px 寬度橫排放標題+show+badge+timestamps+按鈕一定 wrap 醜；垂直堆疊統一。

## Risks / Trade-offs

- **[Risk] 桌機與手機 conditional 散落多檔，未來新 component 容易忘記加 `isMobile` 檢查** → Mitigation：在 `Shared.jsx` 新增 `mobileTable.md` 註解清單列出已 RWD 化的 component；新元件 PR review checklist 加一條「是否考慮 RWD」。
- **[Risk] `window.innerWidth` 在 SSR / 啟動瞬間取值可能不正確** → 本專案無 SSR，CDN React 是純 client，`window` 永遠存在；可忽略。
- **[Risk] 手機 ↑ / ↓ button 連點時樂觀更新與 server 回傳 race** → Mitigation：沿用既有 `dragInFlight` flag 在 PATCH 進行中 disable 兩顆按鈕；失敗回 detail 顯示同 `actionError[row_id]` 既有路徑。
- **[Risk] Drawer 滑動動畫在低階手機卡頓** → Mitigation：用 `transform` 而非 `width/left` 觸發 GPU 加速；`transition: 0.18s ease-out` 短時長；不放 `box-shadow` 動畫。
- **[Trade-off] 不引入 CSS class 模式，每個 component 都要記得呼叫 hook** → 接受。Codebase 一致性 > 些微 boilerplate；總共 < 10 個 page-level component。
- **[Trade-off] `<= 767` 與 `>= 768` 二段切換，iPad mini 直立 768 剛好桌機，邊界顯示可能略擠** → 接受。實機測試若擠再調 768 → 800。
- **[Trade-off] hamburger menu 要點兩次才到 admin sub-tab** → 接受。Admin 桌機慣用、手機只是次要場景。

## Migration Plan

1. **Phase 1（hook + nav）**：`src/Shared.jsx` 加 `useViewport`、改 `TopNav` 條件式渲染 hamburger。`src/App.jsx` 把 `lang` 與 `isMobile` 用 props 注入 TopNav。
2. **Phase 2（modal + 共用）**：`src/Shared.jsx` 改 `FormModal`、`ConfirmModal` 寬度公式。
3. **Phase 3（page-by-page）**：依序改 `PodcastSelect.jsx`、`TranscriptPage.jsx`、`QueryPage.jsx`（drawer）、`AdminPage.jsx`（表單 + sub-tabs）、`QueueTab.jsx`（row stack + ↑↓）。
4. **Phase 4（驗證）**：本機 Chrome DevTools 手機模擬（iPhone 14、iPad mini 直立、Pixel 5）跑一輪 smoke test；Zeabur prod 部署後實機驗證。
5. **Rollback**：每個 phase 都是純 frontend conditional，revert commit 即恢復桌機版型；無資料遷移、無 schema 變更、無破壞性。

## Open Questions

- **iPad 直立（768 px）顯示桌機版型是否可接受**：邊界值，顯示桌機 layout 但寬度剛好夠。實機測試再調整斷點。
- **Drawer 開啟時是否鎖背景捲動**：建議鎖（`document.body.style.overflow = 'hidden'`），但需驗證 React unmount 時還原。
- **手機版字級是否需整體放大**：當前 14px 底字在 360 px 螢幕略小但仍可讀；若使用者反映再調整。
