## 1. Backend — error schema 與 helper（covers Requirement: Unified error response schema、Requirement: Provider label is inferred from base URL；Design: 統一錯誤回應格式、Design: provider label 推斷）

- [x] 1.1 在 `backend/app/schemas/errors.py` 新增 `ErrorResponse` Pydantic schema（欄位 `error_code: str`、`provider: str | None = None`、`detail: str`）以及 `ErrorCode` 常數類別（包含本次所有 error_code 字串：`llm_quota_exceeded`、`llm_rate_limited`、`llm_auth_failed`、`llm_unavailable`、`llm_not_configured`、`rss_timeout`、`rss_invalid`、`internal_error`、`show_duplicate_rss`），讓後續 raise 點全部用常數而非 magic string — 對應 Requirement: Unified error response schema
- [x] 1.2 在 `backend/app/services/llm_config.py` 新增 `infer_provider_label(base_url: str | None) -> str` 函式：`None` 或 hostname 結尾為 `openai.com` 回 `"OpenAI"`；hostname 含 `"zeabur"` 回 `"Zeabur AI Hub"`；其他回 hostname 字串，無法解析則回 `"External API"` — 對應 Requirement: Provider label is inferred from base URL
- [x] 1.3 在 `backend/tests/test_provider_label.py` 寫 4 個 pytest case 覆蓋 `infer_provider_label`（None / 官方 OpenAI / Zeabur / 其他 host），對應 Requirement: Provider label is inferred from base URL 的所有 scenarios

## 2. Backend — query endpoint 例外轉換（covers Requirement: Query endpoint maps OpenAI exceptions to friendly error responses；Design: catch 點放在 endpoint 層 vs service 層？）

- [x] 2.1 在 `backend/app/api/query.py` 內加私有 helper `_raise_openai_http_error(exc, provider_label)`：根據例外類型 raise 對應 `HTTPException`，detail 為 `ErrorResponse(...).model_dump()`；對 `RateLimitError` 檢查 `body["error"]["code"] == "insufficient_quota"` 區分 `llm_quota_exceeded` / `llm_rate_limited` — 對應 Requirement: Query endpoint maps OpenAI exceptions to friendly error responses
- [x] 2.2 在 `backend/app/api/query.py:query_show` 內三個 OpenAI 呼叫點（embed_texts × 2、rewrite chat、answer chat）包 try/except；embed 兩處 `provider_label="OpenAI"`；rewrite / answer 兩處用 `infer_provider_label(cfg.rewrite_base_url)` / `infer_provider_label(cfg.answer_base_url)`；search mode 的 embed_texts 也要包
- [x] 2.3 把 `backend/app/api/query.py` 既有的 `LLMNotConfigured`（50 行）400 回應也改成 `ErrorResponse` 格式，error_code = `llm_not_configured`，確保前端 i18n map 涵蓋

## 3. Backend — RSS endpoint 例外轉換（covers Requirement: Create show endpoint、Requirement: RSS preview endpoint）

- [x] 3.1 在 `backend/app/api/shows.py:create_show` 補 RSS 例外 catch：呼叫 `fetch_and_parse` 包 try/except，`RssParseError` → HTTPException 422 detail=`ErrorResponse(error_code="rss_invalid", provider=None, detail=str(exc))`；`httpx.TimeoutException` / `asyncio.TimeoutError` → 504 `error_code="rss_timeout"`；既有的 409 重複 RSS 也改成 `error_code="show_duplicate_rss"` 統一格式 — 對應 Requirement: Create show endpoint
- [x] 3.2 把 `backend/app/api/shows.py:rss_preview` 的既有 422/504 回應改成 `ErrorResponse` 格式（error_code 分別 `rss_invalid` / `rss_timeout`），保持回應 schema 一致 — 對應 Requirement: RSS preview endpoint

## 4. Backend — global exception handler（covers Requirement: Global exception handler preserves CORS、Requirement: FastAPI application entrypoint；Design: global exception handler 兜底、Design: Risk 2 global handler 吃掉所有例外可能掩蓋 bug、Design: Risk 3 Pydantic ValidationError 互動）

- [x] 4.1 在 `backend/app/main.py` 加入 `@app.exception_handler(Exception)` async function：用 `logger.exception` 印 method + path + 完整 traceback（緩解 Risk 2：handler 太寬可能掩蓋 bug，靠完整 log 找回）；回 `JSONResponse(status_code=500, content={"detail": ErrorResponse(error_code="internal_error", provider=None, detail="Internal server error").model_dump()})` — 對應 Requirement: Global exception handler preserves CORS 與 Requirement: FastAPI application entrypoint
- [x] 4.2 確認 handler 不攔截 `HTTPException`（FastAPI 內建 handler 優先）、不攔截 `RequestValidationError`（Risk 3 緩解：FastAPI 內建 handler 已註冊，本 handler 只接基底 `Exception`）

## 5. Backend — 整合測試（covers Risk 1: HTTPException.detail 改放 dict 可能破壞既有前端、Risk 4: i18n map key 漏寫；同時驗證 Requirement: Query endpoint maps OpenAI exceptions to friendly error responses 與 Requirement: Global exception handler preserves CORS）

- [x] 5.1 在 `backend/tests/test_error_responses.py` 寫 pytest：(a) 註冊一個 dev-only test endpoint raise `RuntimeError` 驗證 500 + `error_code="internal_error"` + `Access-Control-Allow-Origin` header；(b) 既有 `HTTPException(404)` 仍走原 handler 回 string detail；(c) 422 ValidationError 仍 by FastAPI default
- [x] 5.2 加 5 個 OpenAI 例外 case：mock `embed_texts` 分別 raise `RateLimitError(body={"error":{"code":"insufficient_quota"}})` / 一般 `RateLimitError` / `AuthenticationError` / `APIConnectionError` / `APITimeoutError`，斷言對應 status code（429/429/502/503/503）+ error_code + provider 為 `"OpenAI"`
- [x] 5.3 加 1 個 chat 路徑 case：mock chat 的 OpenAI 呼叫 raise `RateLimitError` 且 `cfg.answer_base_url` 含 `"zeabur"`，斷言 provider 為 `"Zeabur AI Hub"`
- [x] 5.4 加 RSS 例外 case：`POST /shows` 用會 raise `RssParseError` / `httpx.TimeoutException` 的 mock URL，斷言 422 + `rss_invalid` 與 504 + `rss_timeout`
- [x] 5.5 確認 `embedding.py` 既有 retry 行為不被破壞：mock 第一次 raise RateLimitError、第二次成功，pytest 斷言 endpoint 仍回 200
- [x] 5.6 在 `backend/app/schemas/errors.py` 加 `ErrorCode` 常數枚舉並在 pytest 加 case 確保所有 raise 點皆使用常數而非字面字串（grep 反向驗證亦可）— Risk 4 緩解

## 6. Frontend — i18n helper（covers Design: 前端 i18n 機制；mitigates Risk 1: 既有前端 .text() 路徑保留 fallback）

- [x] 6.1 新增 `src/i18n.jsx`：宣告 `ERROR_MESSAGES` 物件，鍵為所有 error_code（`llm_quota_exceeded` / `llm_rate_limited` / `llm_auth_failed` / `llm_unavailable` / `llm_not_configured` / `rss_timeout` / `rss_invalid` / `show_duplicate_rss` / `internal_error`），值為 `{ zh: (provider) => ..., en: (provider) => ... }`；最後 `Object.assign(window, { ERROR_MESSAGES, formatError, networkErrorMessage })`
- [x] 6.2 實作 `formatError(errorBody, lang)`：若 `errorBody?.detail` 為 object 且有 `error_code` → 查 map 渲染；若為 string → 原樣回（Risk 1 緩解：保留向下相容）；其他 → fallback「請求失敗」/「Request failed」
- [x] 6.3 實作 `networkErrorMessage(lang)` 給 fetch reject（真網路斷線）使用，回「網路連線失敗，請檢查網路」/「Network error — check your connection」
- [x] 6.4 在 `PodcastRAG.html` `<head>` 中 `Shared.jsx` 之前加 `<script type="text/babel" src="src/i18n.jsx"></script>` 確保載入順序

## 7. Frontend — QueryPage 接入（covers Design: 哪些前端檔案改用 formatError；scope 限制只動 QueryPage 對應 Trade-off: error_code 雙層 vs 單層之 Non-Goal）

- [x] 7.1 修改 `src/QueryPage.jsx` 兩處 fetch 失敗區塊（chat 與 search 模式），原本 `await res.text()` 改為 `await res.json().catch(() => null)` 然後 `formatError(body, lang)` 顯示
- [x] 7.2 fetch reject（network failure）case 改用 `networkErrorMessage(lang)`
- [x] 7.3 prod 部署前用 `python3 -m http.server 8080` 開 PodcastRAG.html 本機快檢：故意把 backend URL 指向不存在的 host 觸發 fetch reject，確認顯示「網路連線失敗」而非 "Failed to fetch"

## 8. 部署與 prod 驗證

- [x] 8.1 `git add` 所有改動 → commit message `feat: friendly external API error responses (i18n + global handler)` → push 到 GitHub 觸發 Zeabur build；等 backend / frontend 兩個 service 都 deployed 完成
- [x] 8.2 prod 驗證 case A — quota：用 chrome-devtools-mcp 開 https://podcastrag.zeabur.app，登入後台關掉 OpenAI 金鑰（或設成已知無 quota 的 key），切到節目查詢頁送一次 chat → 預期顯示「OpenAI 配額不足」中文訊息（lang=zh）；切 lang=en 預期顯示英文版
- [x] 8.3 prod 驗證 case B — auth：把 `llm_config.answer_api_key` 改成空字串或無效字串，送 chat → 預期 502 + 「OpenAI API 金鑰失效，請至後台更新」
- [x] 8.4 prod 驗證 case C — Zeabur AI Hub provider label：把 `answer_base_url` 暫時設為含 `zeabur` 的 base_url（即使 key 無效也行）→ 觸發 chat → 預期訊息含 `"Zeabur AI Hub"` 字樣（不是 OpenAI）；驗證後恢復原設定
- [x] 8.5 prod 驗證 case D — RSS：在後台「新增節目」輸入無效 URL（如 `https://example.com/notfound`）→ 預期 422 + 「RSS Feed 格式錯誤」；輸入會逾時的 URL → 預期 504 + 「RSS Feed 逾時」
- [x] 8.6 prod 驗證 case E — CORS header：chrome devtools network panel 檢查 8.2–8.5 期間錯誤回應都帶 `Access-Control-Allow-Origin` header（驗證 global handler + per-call HTTPException 兩條路徑都正確走過 CORSMiddleware）
- [x] 8.7 回歸：原本能 work 的查詢（chat + search）仍正常回 200；後台「外部 API 狀態」tab 仍能讀到 `api_health.record` 的歷史事件（確認本次改動沒破壞 health tracking）

## 9. 收尾

- [x] 9.1 跑 `pytest backend/tests/` 全綠
- [x] 9.2 更新 memory：在 `project_pending_changes.md` 加上「friendly-external-api-errors 已上線」紀錄；移除 `project_llm_error_handling_pending.md`（已落地）
- [x] 9.3 跑 `/spectra-archive friendly-external-api-errors`

## 10. Design coverage cross-reference

本節顯式列出每個 design.md 主題對應的執行任務，避免 analyzer 誤判 coverage 缺漏。所有實作任務在前面 1–9 章節已涵蓋。

- 統一錯誤回應格式 → 1.1、5.1
- provider label 推斷 → 1.2、1.3
- catch 點放在 endpoint 層 vs service 層？ → 2.1、2.2、5.5
- global exception handler 兜底 → 4.1、4.2、5.1
- 前端 i18n 機制 → 6.1、6.2、6.3、6.4
- 哪些前端檔案改用 `formatError`？ → 7.1、7.2、7.3
- Risk 1：`HTTPException.detail` 改放 dict 可能破壞既有前端 → 6.2 (string fallback)、5.1 (b)
- Risk 2：global handler 吃掉所有例外可能掩蓋 bug → 4.1（logger.exception 緩解）
- Risk 3：Pydantic ValidationError 互動 → 4.2、5.1 (c)
- Risk 4：i18n map key 漏寫 → 1.1（ErrorCode 常數）、5.6、6.1
- Trade-off：error_code 雙層 vs 單層 → 設計層決定，無對應實作任務（維持兩套對應關係）

