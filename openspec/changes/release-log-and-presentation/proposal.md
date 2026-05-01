## Why

PodcastRAG 兩週內累積了 24 個 archived changes（從 RAG MVP 一路演進到 mobile + 友善錯誤），但目前使用者完全看不到這些更新軌跡 —— 既無對外的版本紀錄，也沒有可分享的「系統介紹」管道。同時 `docs/case-studies/` 已累積三份協作方法論文件，沒有曝光途徑。

新增使用者向 Release Log 頁面與獨立 Presentation 頁面，能：
1. 讓使用者（與未來分享對象）看到系統一路長出什麼功能
2. 把已有的案例文件融入簡報，作為「過程心得」轉折段
3. 建立每次 archive 後同步更新 release log 的工作流，避免下次又累積一堆未曝光的成果

## What Changes

- 新增前端頁面 `page === 'release-log'`（TopNav 加入口、雙語、回填 24 筆歷史條目，按里程碑分組逆排）
- 新增前端頁面 `page === 'presentation'`（**TopNav 不加入口**，手動 setState 進入 / URL hash 觸發；左右鍵切換、Esc 退出、≈ 13 張 slide）
- 新增 `src/releaseLog.jsx` 作為唯一資料源（手寫常數陣列），release log 與 presentation 共用
- Presentation 額外手寫 narrative slides（封面 / 系統介紹 / 架構圖 / 數字成長 / 心得 / 下一步 / 結尾），其中 3 張「過程心得」內容濃縮自 `docs/case-studies/` 三份文件
- 數字成長 slide 寫死 snapshot（24 changes / 轉錄集數 / 向量筆數）—— 採方案 A，不打 API
- 簡報頁面完成並驗收後，使用 pptx skill 產一份 `.pptx` 檔（先 ToolSearch 找 skill；找不到從 marketplace 安裝；不自寫 python-pptx 腳本）
- 新增 feedback 記憶 `feedback_release_log_maintenance.md`：每次 `/spectra-archive` 完成後 Claude 主動詢問「要不要補進 release log」並起草該筆 entry，使用者 confirm 後寫入 `releaseLog.jsx`

## Non-Goals

- **不引入打包工具**（Vite / webpack）—— 維持「點開 PodcastRAG.html 即可運行」的開發體驗；release log entries 一律手動補
- **不解析 markdown / archive 自動生成**：白話化由人 / Claude 翻譯，比直接吐 proposal 內容更貼近使用者
- **不打後端 API 取統計數字**：snapshot 寫死，下次更新簡報時手動覆寫常數
- **不在 TopNav 加 Presentation 入口**：簡報為「特殊場合對外展示」用途，不污染日常導覽
- **不引入 reveal.js 或其他簡報框架**：純 React + inline style，與專案既有風格一致
- **不串 i18n 切換到簡報**：簡報固定中文（場合對象多為中文使用者），release log 才走雙語

## Capabilities

### New Capabilities

- `release-log-ui`: 使用者向更新日誌頁面，依里程碑分組顯示版本條目，雙語切換
- `presentation-ui`: 獨立簡報頁面，鍵盤導覽、固定 13 張 slide 結構、共用 release log 資料源

### Modified Capabilities

(none)

## Impact

- Affected specs: 兩個新 capability（release-log-ui / presentation-ui）
- Affected code:
  - New:
    - src/releaseLog.jsx
    - src/ReleaseLogPage.jsx
    - src/PresentationPage.jsx
    - PodcastRAG_presentation.pptx（產出物，由 pptx skill 生成）
  - Modified:
    - PodcastRAG.html（引入新 .jsx）
    - src/App.jsx（兩個新 page case + URL hash listener for presentation）
    - src/Shared.jsx（TopNav 加 release-log 入口）
    - src/i18n.jsx（release log 用雙語字串）
- Memory:
  - New: ~/.claude/projects/-Users-jackylin-Documents-Project-PodcastRAG/memory/feedback_release_log_maintenance.md
