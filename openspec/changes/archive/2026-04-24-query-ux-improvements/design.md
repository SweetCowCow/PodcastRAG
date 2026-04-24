## Context

目前 QueryPage 有三個問題：
1. 右側集數面板仍渲染 `MOCK_EPISODES`（6 筆靜態假資料），無法反映真實轉錄狀態
2. Chat 模式回傳全部 TopK chunks 作為 citations，包含 LLM 未引用的片段，造成雜訊
3. 點擊 citation badge 無任何行為（無法跳轉到逐字稿）

此外開發者目前無法在 Claude Code session 中直接操作瀏覽器，需要手動切換視窗驗證 UI。

## Goals / Non-Goals

**Goals:**
- 集數面板顯示真實資料（标题、集數、轉錄狀態）
- Citation 只顯示 LLM 實際引用的片段
- 點擊 citation 可跳轉至 TranscriptPage 並指定時間點
- 設定 chrome-mcp（Playwright MCP），讓 Claude Code session 可直接操作瀏覽器

**Non-Goals:**
- 不修改集數面板的分頁邏輯（一次載入最多 200 集，超出範圍留待後續處理）
- 不改變 RAG 的 embedding 或 retrieval 邏輯（TopK 仍為 8）
- 不實作逐字稿內容的 diff 或版本比較
- 不替換語意搜尋的 citation 行為（搜尋模式保持現有顯示方式）

## Decisions

### 集數面板改接真實 API

**做法**：QueryPage mount 時 `fetch GET /shows/{show_id}/episodes?limit=200`，結果存入 `episodes` state（初始 `null`，載入中顯示 spinner，失敗顯示錯誤訊息）。`EpisodeCard` 改用 API 欄位：`id`、`title`、`published_at`（格式化為 YYYY-MM-DD）、`duration_seconds`（轉為 mm:ss）、`transcript_status`（`completed` → 已轉錄；其餘 → 待轉錄）。

`GET /shows/{show_id}/episodes` 已存在，回傳 `EpisodeResponse`。需確認 `EpisodeResponse` schema 包含 `transcript_status` 欄位；若無則從後端 episodes endpoint 補上（JOIN transcripts）。

**替代方案排除**：懶加載/分頁 — 節目集數上限 200 集時資料量可控，一次載入避免 UI 複雜度。

### 結構化輸出過濾 citations

**做法**：`answer_with_chunks` 改為要求 LLM 回傳 JSON：
```json
{
  "answer": "...",
  "used_chunk_ids": ["ep:<uuid>@<start_time>", ...]
}
```
使用 `response_format={"type": "json_object"}` 確保 JSON 輸出。後端解析 `used_chunk_ids`，對照 hits 列表過濾出實際使用的片段回傳為 `citations`。

若 `used_chunk_ids` 解析失敗（LLM 輸出格式錯誤），fallback 回傳全部 hits（保持現有行為，不中斷查詢）。

**替代方案排除**：inline 引用標記（如 `[1][2]`）— 需要 regex 解析 answer 文本，與多語言支援相性差；JSON 結構化更可靠。

### Citation 點擊跳轉 TranscriptPage

**做法**：`ChatBubble` 的 citation badge 改為可點擊。點擊後呼叫 props 傳入的 `onOpenEpisode(episodeObj, startTime)` callback。`QueryPage` 透過 `onOpenEpisode` prop 向上傳遞，`App.jsx` 負責導航至 `TranscriptPage` 並傳入 `highlightTime`。

`TranscriptPage` 現有 `selectedEpisode` prop，新增 `highlightTime` prop（秒數，可為 null）。載入後自動 scroll 到對應時間段並以顏色高亮 3 秒。

### Chrome MCP 設定（Playwright MCP）

**做法**：使用 `@playwright/mcp`（Microsoft 官方，支援 Chrome headless/headed）。安裝後在 `.claude/settings.local.json` 的 `mcpServers` 區塊加入：
```json
"mcpServers": {
  "playwright": {
    "command": "npx",
    "args": ["@playwright/mcp@latest"]
  }
}
```
因 `settings.local.json` 不進 git，此設定屬於開發者本機環境設定。

## Risks / Trade-offs

- **JSON 結構化輸出相容性** → 部分 LiteLLM proxy 可能不支援 `response_format=json_object`；`answer_with_chunks` fallback 機制確保不影響可用性
- **episodes 欄位缺少 transcript_status** → 需查後端 schema；若缺少需補 JOIN，可能影響 episodes endpoint 效能（資料量小，可接受）
- **TranscriptPage highlightTime scroll** → TranscriptPage 目前為靜態渲染，需確認 segment 元素是否有 data-time 可供定位

## Migration Plan

1. 後端：確認並補齊 `EpisodeResponse` 的 `transcript_status` 欄位
2. 後端：修改 `answer_with_chunks` 為 JSON 結構化輸出 + fallback
3. 前端：QueryPage 集數面板改接 API
4. 前端：ChatBubble citation 加點擊行為，App.jsx/QueryPage 串接 onOpenEpisode
5. 前端：TranscriptPage 加 highlightTime scroll
6. 環境：安裝 `@playwright/mcp`，更新 `.claude/settings.local.json`
