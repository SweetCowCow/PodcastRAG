## Why

`src/PodcastSelect.jsx` 目前用 `MOCK_SHOWS` 顯示 4 個硬編碼節目，使用者新增 RSS 節目後在 UI 上看不到；點進 QueryPage 時 `show.id` 也是 `'tsmc-era'` 這種字串，與後端 UUID 不符，導致 rag-query change 剛完成的查詢 API 在 UI 上根本打不通。必須把首頁切到真實 `GET /shows`，這條 end-to-end 鏈路才會實際可用。

## What Changes

- `GET /shows` response 新增 `transcribed_count`（非空整數），計算為該 show 下 `transcripts.status = 'completed'` 的 episode 數；前端進度條需要它
- `src/PodcastSelect.jsx` 改為 `useEffect` 掛載時 `fetch(API_BASE + '/shows')`，渲染真實資料；移除 `MOCK_SHOWS` hardcoded 陣列
- 補 loading、error、empty（尚未新增任何 show）三種狀態
- 前端相容新 show shape：
  - `show.name / nameEn` → 統一用 `show.title`（不再雙語）
  - `show.desc / descEn` → 統一用 `show.description`
  - `show.episodes / transcribed` → 用後端 `episode_count` / `transcribed_count`
  - `show.color` → 客戶端以 `show.id` 做 deterministic hash 對應 TOKEN palette（`#6366f1 / #22d3ee / #f59e0b / #22c55e / #ec4899`）
  - `show.host / hostEn / tags / tagsEn / lastUpdate` → 暫不顯示（RSS 未解析這些欄位、或無對應後端欄位）
- `src/QueryPage.jsx` 相容：`showName = show.title`、頂端 badge 讀 `show.transcribed_count`、不再引用 `show.nameEn`

## Non-Goals

- **Episodes 面板串 API**：QueryPage 右側的集數清單仍使用 `MOCK_EPISODES`，另開 `episodes-list-backend` change 處理
- **雙語 title / description**：後端 `shows` 表目前只存單一 `title`，RSS 也不提供 `zh/en` 對照；本 change 不擴充 schema
- **Host / tags metadata**：RSS parser 目前不萃取 `itunes:author` 與 categories；等有實際產品需求再做
- **新增 show 的 UI flow**：目前只能 `POST /shows` curl 觸發，前端「新增節目」UI 由另外的 change 處理
- **同步進度顯示、lastUpdate**：需要另外加欄位（last_synced_at），不在本 change 範圍

## Capabilities

### New Capabilities

（無）

### Modified Capabilities

- `rss-feed`：`List shows endpoint` 的 response shape 擴充 `transcribed_count`

## Impact

- Affected specs: `rss-feed`
- Affected code:
  - `backend/app/schemas/show.py`（`ShowListItem` 新增 `transcribed_count` 欄位）
  - `backend/app/api/shows.py`（`list_shows` 改為 JOIN transcripts 計算 completed 數量）
  - `src/PodcastSelect.jsx`（改為 fetch + loading/error/empty，移除 MOCK_SHOWS；derive color）
  - `src/QueryPage.jsx`（相容新 show shape，移除對 MOCK show 專屬欄位的引用）
