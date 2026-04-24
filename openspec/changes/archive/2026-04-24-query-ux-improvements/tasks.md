## 1. 後端：Episodes endpoint includes transcript status

- [x] 1.1 實作 Requirement: Episodes endpoint includes transcript status——在 `backend/app/schemas/episode.py` 的 `EpisodeResponse` 新增 `transcript_status: str | None` 欄位（值為 `"completed"` / `"processing"` / `"pending"` / `"failed"` / `null`）
- [x] 1.2 在 `backend/app/api/episodes.py::list_episodes` 改寫 query：對 `transcripts` 做 LEFT JOIN，SELECT `transcripts.status` 並映射為 `transcript_status`；調整回傳邏輯讓 `EpisodeResponse.transcript_status` 能正確填入

## 2. 後端：Chat endpoint answers with citations using Tier 2 RAG（結構化輸出過濾 citations）

- [x] 2.1 實作 Requirement: Chat endpoint answers with citations using Tier 2 RAG（結構化輸出過濾 citations）——在 `backend/app/services/rag.py` 修改 `ANSWER_SYSTEM_PROMPT_TEMPLATE`：要求 LLM 回傳 JSON 格式 `{"answer": "...", "used_chunk_ids": ["ep:<uuid>@<start_time>", ...]}`，chunk key 格式與現有 `[ep:<episode_id>@<start_time>]` 標記一致
- [x] 2.2 修改 `backend/app/services/rag.py::answer_with_chunks`：加入 `response_format={"type": "json_object"}` 參數，回傳型別改為 `tuple[str, list[str]]`（answer 文字, used_chunk_ids 列表）；若 JSON 解析失敗則 fallback 回傳 `(raw_text, [])` 表示使用全部 chunks
- [x] 2.3 修改 `backend/app/api/query.py::query_show` chat 分支：接收 `answer_with_chunks` 的 tuple 回傳值，用 `used_chunk_ids` 過濾 `hits`（比對 `ep:<episode_id>@<start_time>` key），fallback 時回傳全部 hits；更新 `ChatResponse` citations 欄位

## 3. 前端：QueryPage episode panel fetches real episodes（集數面板改接真實 API）

- [x] 3.1 實作 Requirement: QueryPage episode panel fetches real episodes——在 `src/QueryPage.jsx` 的 `QueryPage` 元件新增 `const [episodes, setEpisodes] = React.useState(null)` 和 `const [epError, setEpError] = React.useState(null)`；在 `useEffect` 中 fetch `${API_BASE}/shows/${show.id}/episodes?limit=200`，成功設 `setEpisodes(data)`，失敗設 `setEpError(err.message)`
- [x] 3.2 將 `rightContent` 從渲染 `MOCK_EPISODES` 改為渲染 `episodes` state：loading（`episodes === null && !epError`）顯示 spinner；error 顯示錯誤訊息；loaded 渲染 `episodes.map(ep => <EpisodeCard ... />)`
- [x] 3.3 修改 `EpisodeCard` 改用 API 欄位：`ep.title`（移除 `ep.titleEn`）、`ep.published_at` 格式化為 `YYYY-MM-DD`、`ep.duration_seconds` 格式化為 `mm:ss`（使用現有 `formatTimestamp`）、`ep.transcript_status === 'completed'` 判斷是否已轉錄（取代 `ep.transcribed`）；同步更新 `ResizableLayout` 的 `epCount` 為 `episodes?.filter(e => e.transcript_status === 'completed').length ?? transcribedCount`

## 4. 前端：Citation click navigates to transcript with highlight

- [x] 4.1 實作 Requirement: Citation click navigates to transcript with highlight（Citation 點擊跳轉 TranscriptPage）——修改 `src/QueryPage.jsx::ChatBubble`：citation badge 加 `onClick` handler，呼叫 props 傳入的 `onCitationClick(citation)` callback（`citation` 含 `episode_id`、`start_time`）；加上 `cursor: 'pointer'` 和 hover 效果
- [x] 4.2 在 `QueryPage` 元件加入 `onCitationClick` prop，實作為 `(citation) => onOpenEpisode({ id: citation.episode_id, title: citation.episode_title }, citation.start_time)`；將此 callback 傳入 `ChatBubble`
- [x] 4.3 修改 `src/TranscriptPage.jsx`：新增 `highlightTime` prop（秒數，`null` 表示無高亮）；在 segments 渲染完成後（`useEffect` 監聽 segments 載入），找到 `start_time` 最接近 `highlightTime` 的 segment，scroll 到該元素並套用 3 秒背景高亮（CSS transition fade，使用 `TOKEN.accent + '33'` 為高亮色）
- [x] 4.4 在 `src/App.jsx` 的 `onOpenEpisode` handler 新增 `highlightTime` 參數，傳入 `TranscriptPage` 的 `highlightTime` prop；確認 `QueryPage` 的 `onOpenEpisode` call site 能接收第二個參數

## 5. 環境：Chrome MCP 設定（Playwright MCP）

- [x] 5.1 執行 `npm install -g @playwright/mcp@latest` 安裝 Playwright MCP（若系統未安裝 npm 則改用 `npx` 直接執行不需全域安裝）
- [x] 5.2 在 `.claude/settings.local.json` 的頂層新增 `"mcpServers"` 區塊：`{ "playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] } }`；確保不覆蓋現有 `permissions` 區塊

## 6. 驗證

- [x] 6.1 重啟 backend（`docker compose restart backend`）；`curl http://localhost:8000/shows/{show_id}/episodes?limit=5 | python3 -m json.tool` 確認回應包含 `transcript_status` 欄位
- [x] 6.2 瀏覽器開 `PodcastRAG.html`：進入 QueryPage 確認右側集數面板顯示真實集數（非 EP142～EP137 假資料）；已轉錄集數顯示「已轉錄」badge，未轉錄顯示「待轉錄」且無法點擊
- [x] 6.3 Chat 問「請列出所有已轉錄集數的標題」；確認回應跨多集回答，citations 只顯示回答中有引用的片段（非全部 TopK）
- [x] 6.4 點擊 citation badge；確認跳轉至 TranscriptPage 並高亮對應時間段
