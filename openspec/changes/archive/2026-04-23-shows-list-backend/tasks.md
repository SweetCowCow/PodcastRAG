## 1. 後端 Response Shape

- [x] 1.1 實作 Requirement: List shows endpoint 的 response 擴充——在 `backend/app/schemas/show.py` 的 `ShowListItem` 新增 `transcribed_count: int` 欄位；保留現有 `episode_count`
- [x] 1.2 實作 Scenario: Shows listed with episode and transcript counts / Show with no transcribed episodes——在 `backend/app/api/shows.py::list_shows` 改寫 query：`SELECT Show, COUNT(Episode.id), COUNT(Episode.id) FILTER (WHERE Transcript.status = 'completed') FROM shows LEFT OUTER JOIN episodes ON ... LEFT OUTER JOIN transcripts ON transcripts.episode_id = episodes.id GROUP BY shows.id ORDER BY shows.created_at DESC`；`_show_to_response` 新增 `transcribed_count` 參數

## 2. 前端 PodcastSelect

- [x] 2.1 `src/PodcastSelect.jsx`：移除 `MOCK_SHOWS`；加 `const [shows, setShows] = useState(null)`、`const [error, setError] = useState(null)`；掛載時 `fetch(API_BASE + '/shows')` → `setShows(data)`（失敗 → `setError(err.message)`）
- [x] 2.2 渲染三態：loading（`shows === null && !error`）顯示「載入中...」/「Loading...」；error 顯示紅字錯誤；empty（`shows.length === 0`）顯示「尚未新增節目」引導文字
- [x] 2.3 `ShowCard` 改用後端欄位：`title` 取代 `name/nameEn`、`description` 取代 `desc/descEn`、`rss_url` 取代 `rss`、`image_url` 取代 `cover`、`episode_count`/`transcribed_count` 取代 `episodes/transcribed`；移除 `host/hostEn/tags/tagsEn/lastUpdate` 的 UI block；`color` 由 `deriveColor(show.id)` 計算（對 `id` 做 FNV-1a 32-bit hash → `palette[hash % palette.length]`，`palette = ['#6366f1','#22d3ee','#f59e0b','#22c55e','#ec4899']`）
- [x] 2.4 搜尋過濾器 `filtered`：改為 `(title + description + rss_url).toLowerCase().includes(q)`

## 3. 前端 QueryPage 相容

- [x] 3.1 `src/QueryPage.jsx`：`showName = show.title`（移除 `show.nameEn` 分支）；頂端 badge 讀 `show.transcribed_count`；RAG 範圍提示讀 `show.transcribed_count`；移除對 `show.color` 以外其他 mock 專屬欄位的引用（若有遺漏的話維持）

## 4. 本地驗證

- [x] 4.1 `docker compose build backend && docker compose up -d backend`；`curl http://localhost:8000/shows | python3 -m json.tool` 驗回應包含 `transcribed_count`；對 b89a4af2 所屬 show（`fdd5a450-5190-4c8d-9770-bd7c57aad8f2`）確認 `transcribed_count >= 1`
- [x] 4.2 瀏覽器開 `PodcastRAG.html`：首頁看到真實 show；點進 QueryPage 後頂端 badge 顯示「N 集已轉錄」對應後端值；Chat 問「What is this episode about?」能收到帶 citations 的真實回應
