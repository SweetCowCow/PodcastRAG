## Context

PodcastRAG 是純 CDN + Babel Standalone 的 React 專案，無 build 步驟。`page` state 走 switch-case 路由，無 React Router。`docs/case-studies/` 三份協作方法論文件不進 git（feedback memory 規定），但本次要把濃縮版內容**直接 inline 寫進** Presentation 元件，不從 docs 動態讀取，因此不違反該規則。

過去 24 個 archived changes 分布於 2026-04-19 至 2026-05-01，自然形成四個主題群組（RAG MVP / 排程系統 / 平行轉錄+Queue UI / Mobile+友善錯誤），可作為里程碑分界。

## Goals

- Release Log 與 Presentation **共用單一資料源** `src/releaseLog.jsx`，後續補一筆 entry 兩處同步更新
- Presentation 路由走 URL hash（`#presentation`）而非 TopNav 按鈕，避免污染主導覽
- 簡報導出 `.pptx` 走官方/marketplace skill，**不手寫 python-pptx 腳本**（避免維護負擔）

## Non-Goals

- 不引入打包工具（Vite / webpack 等）—— 維持點開 HTML 即可運行
- 不串 i18n 到 Presentation —— 固定中文，簡化資料結構
- 不打 backend API 取數字 —— snapshot 寫死

## Decisions

### Release log 資料 schema

`src/releaseLog.jsx` export 一個常數陣列，每筆 entry 結構：

```jsx
{
  date: '2026-05-01',          // archive 日期，逆排
  slug: 'friendly-external-api-errors', // 對應 archive 資料夾名
  milestone: 'v0.4',            // 用於分組
  tag: 'enhancement',           // 'feature' | 'fix' | 'enhancement' | 'ui'
  title: { zh: '...', en: '...' },     // 白話標題
  summary: { zh: '...', en: '...' },   // 1–2 句白話摘要
}
```

**為什麼選這個 schema**：里程碑分組需要 `milestone`；逆排序需要 `date`；雙語顯示需要 nested `{ zh, en }`；tag 用於前端 Badge 顯色。

**替代方案否決**：runtime fetch markdown + 解析 → 違反不打包原則、且白話化品質難保證。

### Presentation 路由與導覽

- 進入方式：URL hash 變成 `#presentation` 時 `App.jsx` 切到該 page，hash 清空時退出
- Slide 切換：`useEffect` 綁 `keydown`，左右鍵切換、Esc 觸發 hash 清空、空白鍵下一張
- 不在 TopNav / 任何頁面放按鈕進入 —— 使用者要展示時手動改網址

**為什麼選 hash**：純前端、無路由套件、可直接分享連結（如 prod URL `#presentation` 直接進簡報）；跟現有 `page` state 互斥但可雙向同步。

**替代方案否決**：藏在後台 admin 子 tab → 後台對使用者來說不該有展示頁；React Router → 大砲打蚊子。

### Slide 內容組織

13 張 slide 拆兩類：
- **Narrative slides**（手寫）：封面、系統介紹、架構圖、4 張里程碑串場、數字成長、3 張過程心得、下一步、結尾
- **Data-driven**：里程碑 slide 從 `releaseLog.jsx` 過濾 `milestone === 'v0.x'` 動態列出該版本所有 entry

過程心得三張內容**濃縮**自 `docs/case-studies/`（不全文搬），每張只保留：問題一句話、轉折一句話、學到的事一句話。

### pptx 生成流程

1. Presentation 頁面開發完成、瀏覽器驗收 OK 後
2. 用 ToolSearch 找 `pptx` / `powerpoint` 相關 skill
3. 找不到 → 提示使用者從 marketplace 安裝（`/plugin marketplace` 或對應指令）
4. 安裝後用該 skill 生成 `PodcastRAG_presentation.pptx`，內容對齊網頁版 13 張
5. 此 .pptx 檔案不進 git（與 case studies 同類處理；新增 `.gitignore` 規則）

**為什麼不自寫腳本**：python-pptx 要管 layout / theme / 字型，自寫易出醜；marketplace skill 預期已封裝好版面。

## Risks / Trade-offs

- **Snapshot 數字會過期** → 在 `releaseLog.jsx` 頂端註記 `STATS_AS_OF` 日期常數，slide 顯示「截至 YYYY-MM-DD」；下次更新時人為提醒
- **24 筆回填白話化品質不一致** → Claude 統一翻譯，使用者最後 review 一輪
- **pptx skill 不存在** → 流程已定義 fallback（marketplace 安裝），最壞情況是延後 .pptx 產出但網頁版可單獨上線
- **URL hash 進簡報但使用者誤打開** → 簡報不是機密，看到也無妨；接受此風險

## Migration Plan

1. 開發 release log + presentation 頁面（單一 commit 或拆兩個 commit）
2. push → Zeabur prod 自動部署
3. chrome-devtools-mcp 全程驗證（含鍵盤導覽、雙語切換）
4. 驗收 OK 後跑 pptx skill 生成檔案
5. 寫入 feedback memory `feedback_release_log_maintenance.md`

無 rollback 風險（純前端新增頁面，不動既有功能）。

## Open Questions

(none — 討論階段已收斂)
