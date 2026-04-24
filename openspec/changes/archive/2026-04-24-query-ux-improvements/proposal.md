## Why

QueryPage 的右側集數面板仍使用假資料（MOCK_EPISODES），RAG 查詢回答偶爾只涉及單一集數而非跨集，引用來源顯示所有 TopK 片段（包含未使用的），且目前沒有方法讓開發者透過瀏覽器自動化測試頁面行為。

## What Changes

- 右側集數面板改接 `GET /shows/{show_id}/episodes` 真實 API，顯示真實集數與轉錄狀態
- RAG chat 模式改為結構化輸出：LLM 回傳 JSON 含 `answer` 與 `used_chunk_ids`，後端過濾只回傳實際使用的片段作為 citations
- Citation badge 點擊後跳轉至 TranscriptPage 並高亮對應時間段
- 在 `.claude/settings.local.json` 中設定 chrome-mcp，讓 Claude Code session 可直接操作瀏覽器

## Capabilities

### New Capabilities

- `episode-list-api`: QueryPage 右側欄透過 `GET /shows/{show_id}/episodes` 取得真實集數列表，含分頁、轉錄狀態

### Modified Capabilities

- `rag-query`: Chat 模式改為結構化輸出（`answer` + `used_chunk_ids`），後端只回傳已使用片段的 citations；移除「回傳全部 TopK」行為

## Impact

- Affected specs: `episode-list-api`（新）、`rag-query`（修改 citations 回傳邏輯）
- Affected code:
  - `src/QueryPage.jsx`（集數面板、citation 點擊跳轉）
  - `backend/app/api/query.py`（結構化輸出 + citations 過濾）
  - `backend/app/services/rag.py`（answer_with_chunks 改為結構化 prompt）
  - `backend/app/schemas/query.py`（ChatResponse 欄位調整）
  - `.claude/settings.local.json`（chrome-mcp 設定）
