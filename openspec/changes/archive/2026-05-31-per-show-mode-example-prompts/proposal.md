## Why

新使用者進到某個節目的查詢頁時，三個模式（索引／語意／對話）的輸入框只有通用提示，不知道「針對這個節目」可以問什麼。既有的 `TrendingQueriesChips`（該節目 7 日熱搜）能引導，但新上架或低流量節目沒有足夠熱搜資料（冷啟動），引導就消失。需要一套「每節目 × 每模式」的引導範例問題，在沒有熱搜時也能教使用者怎麼用。

## What Changes

- 三模式輸入框各加一句 per-mode 通用 placeholder（靜態 i18n）。
- 輸入框上方既有 chip 槽位顯示「該節目 × 該模式」的可點擊範例問題：trending 有足夠資料就顯示熱搜；冷啟動（trending 不足）改顯示 LLM 為該節目各模式預產的 2–3 題。
- 後端：LLM 用既有 `episodes.ai_summary` / `episodes.guests` / topic terms 當素材，為每節目各模式預產範例問題；存 DB；ingest 完成後鏈式產生，並提供 admin 一鍵 batch backfill。
- 新增 GET endpoint 讓前端冷啟動取用預產範例。
- 範例為「預產 + 快取」，不在每次查詢時即時生成（控成本）。

## Non-Goals

- 不改檢索 / 答案 / RAG 邏輯。
- 不做引用來源呈現重構（並行 change `unified-segment-citation-card`）。
- 不即時為每次查詢生成範例（一律預產 + 快取）。
- 不改 `trending-queries` 既有行為與計分（只在它資料不足時 fallback 到預產範例）。

## Capabilities

### New Capabilities

- `show-mode-example-prompts`: 每節目 × 每模式的引導範例問題 — LLM 預產 + DB 儲存 + GET endpoint + admin batch backfill；前端 per-mode placeholder 與「trending 優先、冷啟動 fallback 預產範例」的 chip 顯示行為。

### Modified Capabilities

(none)

## Impact

- Affected specs:
  - New: `show-mode-example-prompts`
- Affected code:
  - New:
    - `backend/app/models/show_example_prompt.py`（per-show-per-mode 範例問題資料表 model）
    - `backend/app/services/example_prompts.py`（LLM 生成 + 取素材 + 寫入服務）
    - `backend/app/api/example_prompts.py`（GET endpoint + admin backfill endpoint）
    - 一支 alembic migration（建 `show_example_prompts` 表）
  - Modified:
    - `backend/app/main.py`（掛新 router）
    - `backend/app/services/ai_step_resolver.py` 或對應處（沿用 `ai_steps` 取 LLM endpoint/model，若需新 step key）
    - `src/i18n.jsx`（三模式 placeholder 字串 + 範例 chip 相關文案）
    - `src/TrendingQueriesChips.jsx`（trending 不足時 fallback 打新 endpoint 取預產範例）
    - `src/QueryPage.jsx`（三 tab 的 Input 套用 per-mode placeholder；chip 槽位接 fallback）
    - `backend/app/workers/` 內轉錄/摘要完成的鏈式 enqueue 處（ingest 完成後觸發範例預產，參考 `episode-ai-summary` 鏈式模式）
  - Removed: 無
