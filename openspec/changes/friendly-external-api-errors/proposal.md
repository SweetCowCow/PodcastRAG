## Why

當外部 API（OpenAI、Zeabur AI Hub、RSS 來源）失敗時，後端 endpoint 沒有 catch 對應例外，例外從 router bubble 到 Starlette `ServerErrorMiddleware` 直接回 500。Starlette 的 `CORSMiddleware` 不會替 unhandled exception 附加 CORS header，瀏覽器將 500 視為網路錯誤，前端 `fetch` 只能拿到 `"Failed to fetch"`，使用者無法分辨是「網路斷線」、「後端死了」還是「OpenAI quota 用光」。

2026-05-01 使用者 OpenAI quota 用光時實際發生：`POST /shows/{id}/query` 直接顯示 "Failed to fetch"，必須翻 backend log 才知道是 `RateLimitError`。隨著 LLM provider 已支援 Zeabur AI Hub（OpenAI-compatible base_url），未來 Zeabur 餘額不足會以同樣模式噴 `openai.RateLimitError`，使用者更難自我診斷。

## What Changes

- 新增 `app.exception_handler(Exception)` global handler 兜底所有 unhandled exception，回 JSON `{error_code, provider?, detail}` 500，**走 FastAPI 中介層 → CORS header 正確附加** → 前端能讀到 body
- `app/api/query.py` 三個 OpenAI 呼叫點（embed_texts × 2、rewrite chat、answer chat）catch `openai.RateLimitError` / `AuthenticationError` / `APIConnectionError` / `APITimeoutError`，依例外類型回對應 HTTP status code（429 / 502 / 503）+ `error_code`
- 新增 `app/services/llm_config.py:infer_provider_label(base_url)` helper：`None` / OpenAI 官方 → `"OpenAI"`；含 `"zeabur"` → `"Zeabur AI Hub"`；其他 → URL hostname
- 後端錯誤 detail 永遠以英文 fallback 字串回應；機器可讀的 `error_code` + `provider` 由前端 i18n map 映射成中／英文文案
- `app/api/shows.py:create_show` 補上 RSS 例外 catch（`RssParseError` → 422 `rss_invalid`、`httpx.TimeoutException` → 504 `rss_timeout`）
- 新增 `app/schemas/errors.py` 定義 `ErrorResponse` schema，所有 HTTP error 走統一格式
- 前端新增 `src/i18n.jsx`（或在 `Shared.jsx` 內）`ERROR_MESSAGES` map 與 `formatError(errorBody, lang)` helper；`QueryPage.jsx` 等 fetch 失敗點改用此 helper 顯示錯誤
- pytest 覆蓋：每種 OpenAI 例外類型 → 對應 status code + error_code 各一個 case；global handler smoke test；RSS 例外 case

## Non-Goals

- **不動 worker（`app/workers/tasks.py`）**：Celery task 例外已透過 retry + `api_health.record` 上報，使用者透過「外部 API 狀態」tab 能看到；Celery 不走 HTTP 也無 CORS 問題
- **不做前端 hint「請檢查外部 API 狀態 tab」**：後端 `error_code` + `provider` 已能組出夠精準的訊息（例：「Zeabur AI Hub 配額不足，請至 Zeabur 後台加值」），不需要再加二層提示
- **不做 retry／degraded mode**：純錯誤訊息友善化，不改變現有重試策略（embedding service 內部既有 3 次 backoff 維持原樣）
- **不重寫 `api_health.py`**：本次只用其既有的 `classify_error()`／`record()`；error_code 對照表是新的、互不衝突

## Capabilities

### New Capabilities

(none — 都是修改既有行為)

### Modified Capabilities

- `backend-core`: 新增 global exception handler；統一 ErrorResponse schema；所有 HTTP 錯誤回應格式從散裝 `{detail: str}` 統一為 `{error_code, provider?, detail}`
- `rag-query`: `POST /shows/{id}/query` 對 OpenAI 例外的處理新增 4 種 status code 對照與 `error_code`，包含 provider label 推斷
- `rss-feed`: `create_show` endpoint 對 RSS 解析例外補上對應 status code 與 error_code

## Impact

- Affected specs: `backend-core`、`rag-query`、`rss-feed`
- Affected code:
  - New:
    - `backend/app/schemas/errors.py`
    - `backend/tests/test_error_responses.py`
    - `src/i18n.jsx`
  - Modified:
    - `backend/app/main.py`（加 global exception handler）
    - `backend/app/api/query.py`（per-call try/except）
    - `backend/app/api/shows.py`（補 create_show RSS 例外 catch）
    - `backend/app/services/llm_config.py`（加 `infer_provider_label`）
    - `src/Shared.jsx`（匯出 i18n helper 至 window；或新檔 src/i18n.jsx 經 Shared 匯出）
    - `src/QueryPage.jsx`（fetch 錯誤改用 formatError）
    - `PodcastRAG.html`（若新增 src/i18n.jsx 需要載入）
  - Removed: (none)
- 使用者影響：原本 "Failed to fetch" 的場景會看到具體可診斷訊息；現有正確路徑的 200 回應不變
- 部署影響：純應用層改動，無 migration、無新依賴
