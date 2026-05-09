## 1. Single Source of Truth for Release Data — schema 與資料

- [x] 1.1 在 `src/releaseLog.jsx` 的 entry shape 註解新增 optional 欄位 `summaryBullets?: { zh: string[], en: string[] }`，標明 2-4 bullets 約束
- [x] 1.2 為 v1.4 freemium-launch entry 補一筆 `summaryBullets`，zh / en 各 3 個 bullets，內容由現有 `summary` 提煉最重要的 user-facing 變動

## 2. Entry Body Collapsed By Default With Click-To-Expand — 折疊行為

- [x] 2.1 在 `src/ReleaseLogPage.jsx` 把每個 entry 拆成「Header 區」+「Body 區」；Header 永遠 render、Body 用 `expanded` boolean 條件渲染
- [x] 2.2 用 `useState` 維護 `expandedSlugs` set；header `onClick` 切換對應 slug；確保多個 entry 可獨立展開不互斥
- [x] 2.3 預設 state 為空 set（page 載入時所有 body 隱藏）
- [x] 2.4 Header 內加 chevron `<Icon name="chevron-right">`，expanded 時 `transform: rotate(90deg) + transition: transform 0.15s`

## 3. Release Log Entry Listing — Header Row 排版

- [x] 3.1 Header row 內排版順序 = date + tag Badge + title + summaryBullets + chevron
- [x] 3.2 Body region 渲染既有 localized summary 內容（expanded 時才出現）

## 4. Header Row Shows Summary Bullets — bullets 渲染

- [x] 4.1 在 Header 區條件渲染 `entry.summaryBullets?.[lang]`：非空陣列時 render `<ul>` 列表，使用 `TOKEN.textSecondary` 文字色
- [x] 4.2 缺欄位 / 空陣列時整段不 render，無空 bullet 區

## 5. URL Hash Auto-Expands Targeted Entry — anchor 行為

- [x] 5.1 ReleaseLogPage mount effect 讀 `window.location.hash`，去 `#` 後對照 RELEASE_LOG 的 slug；match 則加入 `expandedSlugs` 初始集合
- [x] 5.2 同 effect 呼叫 `document.getElementById(slug)?.scrollIntoView({ behavior: 'smooth', block: 'start' })` 把該 entry 帶入 viewport
- [x] 5.3 每個 entry header container 掛 `id={entry.slug}`，給 anchor + scrollIntoView 用
- [x] 5.4 Hash 不存在或 slug 對不上 RELEASE_LOG 時：維持全部 collapsed、不滾動

## 6. Header Row Is Keyboard Accessible — 鍵盤可用性

- [x] 6.1 Header 改用 `<button type="button">` 包整段，使其自動取得 Tab focus 與 Enter / Space toggle
- [x] 6.2 加 `:focus-visible` outline（`TOKEN.accent` 2px solid），確保鍵盤焦點可見
- [x] 6.3 Header hover 加 `cursor: pointer` 與背景色從 `TOKEN.surface` → `TOKEN.surfaceRaised`
- [x] 6.4 取消 header 內子元素（Badge 等）的 `stopPropagation`，使點擊冒泡到 button

## 7. 端對端驗證

- [x] 7.1 瀏覽器目視驗證：預設全收合、點 header 展開/收合、chevron 旋轉、多 entry 獨立展開、summaryBullets 有/無 entry 渲染正確
- [x] 7.2 鍵盤驗證：Tab 走過所有 header、Enter / Space 切換、focus outline 可見
- [x] 7.3 Hash 驗證：`/release-log#<v1.4-slug>` 自動展開且 scroll 進視窗；`/release-log#bogus` 全收合無滾動
- [x] 7.4 雙語驗證：切換 zh / en 後 header（含 bullets）同步翻譯
- [x] 7.5 Mobile viewport（<768px）驗證：timeline 垂直線左貼齊、card 滿寬、collapse/expand 互動正常
