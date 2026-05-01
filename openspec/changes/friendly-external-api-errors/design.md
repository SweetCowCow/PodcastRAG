## Context

PodcastRAG 後端使用 FastAPI + Starlette 中介層架構，前端為純 React（無 bundler）以 `lang === 'zh' | 'en'` 條件渲染雙語介面。當前外部 API 例外處理散落各處：

- `app/services/embedding.py` 已有 `_embed_with_retry`（OpenAI Embeddings 重試 3 次）+ `api_health.record`，但失敗時直接 `raise` 原始例外
- `app/services/rag.py` 同樣記錄健康事件後再 `raise`
- `app/api/query.py` 三個外部呼叫點完全沒包 try/except，例外從 thread bubble 到 endpoint 再到 router
- `app/api/shows.py:rss_preview` 已 catch `RssParseError` / `httpx.TimeoutException`，但 `create_show` 路徑沒 catch
- `app/main.py` 只掛 `CORSMiddleware`，沒有任何 `@app.exception_handler`

Starlette 行為：unhandled exception 由 `ServerErrorMiddleware`（middleware 棧最外層）捕獲，回 plain text 500，**不會觸發 user 自訂的中介層**（包含 CORSMiddleware）。FastAPI 的 `@app.exception_handler` 則註冊在 router 內，回應仍會經過 user middleware → CORS header 正確附加。

LLM provider 透過 `app/models/llm_config.py` 的 `answer_base_url` / `rewrite_base_url` 欄位由使用者於 admin UI 配置，目前實際使用 `https://api.openai.com/v1` 與 Zeabur AI Hub（`https://*.zeabur.app/v1`，OpenAI-compatible），未來不排除其他 OpenAI-compatible provider。

## Goals / Non-Goals

**Goals:**

- 後端任何 unhandled exception 回應都帶 CORS header（前端能讀到 body）
- 前端能根據 `error_code` 顯示精準雙語訊息，不再出現 "Failed to fetch"（除非真的網路斷線）
- 訊息能分辨 OpenAI 官方 vs Zeabur AI Hub vs 其他 provider（使用者知道去哪裡加值／更新金鑰）
- 既有正確路徑（200 回應）行為不變
- 既有 `api_health` tracking 不受影響（仍然 record 全部失敗事件，獨立於 HTTP 回應格式）

**Non-Goals:**

- 不改 worker 例外處理（Celery retry + api_health 已足夠）
- 不做使用者可見的 retry 控制（embedding 內建 backoff 維持不變）
- 不做錯誤監控／告警（屬另一範圍）
- 不重寫 `api_health.classify_error`；它有自己的六分類用途（健康 dashboard），與本次的 `error_code` 是兩套對應不同層級

## Decisions

### 1. 統一錯誤回應格式

所有 HTTP 4xx/5xx 改為以下 schema（`backend/app/schemas/errors.py`）：

```python
class ErrorResponse(BaseModel):
    error_code: str          # machine-readable, snake_case
    provider: str | None     # human-readable, e.g. "OpenAI", "Zeabur AI Hub"
    detail: str              # English fallback / log
```

`error_code` 對照表：

| error_code | HTTP | 觸發條件 |
|-----------|------|---------|
| `llm_quota_exceeded` | 429 | `openai.RateLimitError` 且 body.error.code == `insufficient_quota` |
| `llm_rate_limited` | 429 | `openai.RateLimitError` 其他情形 |
| `llm_auth_failed` | 502 | `openai.AuthenticationError` |
| `llm_unavailable` | 503 | `openai.APIConnectionError` 或 `openai.APITimeoutError` |
| `rss_timeout` | 504 | `httpx.TimeoutException` 或 `asyncio.TimeoutError` |
| `rss_invalid` | 422 | `RssParseError` |
| `llm_not_configured` | 400 | `LLMNotConfigured`（既有，沿用） |
| `internal_error` | 500 | global handler 兜底（其他 unhandled） |
| `validation_error` | 422 | FastAPI / Pydantic（保留 default 行為） |

### 2. Provider label 推斷

新增 `app/services/llm_config.py:infer_provider_label(base_url: str | None) -> str`：

```python
def infer_provider_label(base_url: str | None) -> str:
    if not base_url:
        return "OpenAI"
    host = urlparse(base_url).hostname or ""
    if host.endswith("openai.com"):
        return "OpenAI"
    if "zeabur" in host:
        return "Zeabur AI Hub"
    return host or "External API"
```

`embedding.py` 走死的官方 endpoint → 永遠 `"OpenAI"`；`rag.py` 內 chat / rewrite 走 LLMConfig → 由 `infer_provider_label(cfg.answer_base_url)` 動態決定。

### 3. catch 點放在 endpoint 層 vs service 層？

選 **endpoint 層**（`app/api/query.py`）。

原因：
- service 層（`embedding.py` / `rag.py`）的呼叫者除了 web endpoint 還有 worker（背景任務），worker 需要原始例外觸發 Celery retry，不能在 service 層轉成 `HTTPException`
- 既有 `api_health.record` 在 service 層 finally 區塊內已執行，endpoint catch 後再 `raise HTTPException` 不會 double-record

寫法（示意）：

```python
# query.py
try:
    query_embedding = await asyncio.to_thread(embed_texts, [payload.question])
except openai.RateLimitError as exc:
    code = "llm_quota_exceeded" if _is_insufficient_quota(exc) else "llm_rate_limited"
    raise HTTPException(429, detail=ErrorResponse(
        error_code=code, provider="OpenAI",
        detail=str(exc) or "OpenAI rate limit",
    ).model_dump())
except openai.AuthenticationError as exc:
    raise HTTPException(502, detail=ErrorResponse(
        error_code="llm_auth_failed", provider="OpenAI",
        detail="OpenAI authentication failed",
    ).model_dump())
except (openai.APIConnectionError, openai.APITimeoutError) as exc:
    raise HTTPException(503, detail=ErrorResponse(
        error_code="llm_unavailable", provider="OpenAI",
        detail="OpenAI unreachable",
    ).model_dump())
```

抽 helper `_raise_openai_http_error(exc, provider_label)` 共用三處呼叫點（embed / rewrite / answer）。

### 4. global exception handler 兜底

```python
# main.py
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception in %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="internal_error",
            provider=None,
            detail="Internal server error",
        ).model_dump(),
    )
```

注意：`HTTPException` 不會走到這個 handler（FastAPI 內建 handler 優先），所以 endpoint 顯式 raise 的 `HTTPException` 仍按 4xx/5xx 流程走。

`HTTPException.detail` 改放整個 `ErrorResponse` dict，FastAPI 的 default `http_exception_handler` 會直接將 detail 序列化進 JSON `{"detail": {...}}`。前端讀 `body.detail.error_code` 取值。

### 5. 前端 i18n 機制

新增 `src/i18n.jsx`，匯出 `ERROR_MESSAGES` map 與 `formatError(errorBody, lang)`：

```jsx
const ERROR_MESSAGES = {
  llm_quota_exceeded: {
    zh: (p) => `${p} 配額不足，請至 ${p === 'OpenAI' ? 'OpenAI' : 'Zeabur'} 後台檢查餘額`,
    en: (p) => `${p} quota exceeded — check your account balance`,
  },
  llm_rate_limited: {
    zh: (p) => `${p} 速率限制，請稍候再試`,
    en: (p) => `${p} rate limit reached — please retry shortly`,
  },
  llm_auth_failed: {
    zh: (p) => `${p} API 金鑰失效，請至後台更新`,
    en: (p) => `${p} API key invalid — update it in admin`,
  },
  llm_unavailable: {
    zh: (p) => `無法連線至 ${p}，請稍後重試`,
    en: (p) => `Cannot reach ${p} — please retry later`,
  },
  llm_not_configured: {
    zh: () => 'LLM 尚未在後台設定',
    en: () => 'LLM is not configured in admin',
  },
  rss_timeout: {
    zh: () => 'RSS Feed 逾時',
    en: () => 'RSS feed timed out',
  },
  rss_invalid: {
    zh: () => 'RSS Feed 格式錯誤',
    en: () => 'RSS feed is invalid',
  },
  internal_error: {
    zh: () => '伺服器內部錯誤，請稍後重試',
    en: () => 'Internal server error — please retry later',
  },
};

function formatError(errorBody, lang) {
  // errorBody.detail can be: ErrorResponse dict (new) | string (legacy) | undefined
  const d = errorBody?.detail;
  if (d && typeof d === 'object' && d.error_code) {
    const map = ERROR_MESSAGES[d.error_code];
    if (map) return map[lang](d.provider || '');
    return d.detail || (lang === 'zh' ? '未知錯誤' : 'Unknown error');
  }
  if (typeof d === 'string') return d;
  return lang === 'zh' ? '請求失敗' : 'Request failed';
}

// fetch 失敗（網路斷線真的拿不到 response）
function networkErrorMessage(lang) {
  return lang === 'zh' ? '網路連線失敗，請檢查網路' : 'Network error — check your connection';
}

Object.assign(window, { formatError, networkErrorMessage });
```

`PodcastRAG.html` 在 `Shared.jsx` 之前載入 `src/i18n.jsx`，確保所有頁面可用。

### 6. 哪些前端檔案改用 `formatError`？

本次只改 **`src/QueryPage.jsx`**（query 流程是這次 bug 主要受害者）。其他 fetch 點（AdminPage / TranscriptPage 等）保留現狀，避免 scope 灌水；後續若有需求再做（已在 Non-Goals）。

## Risks / Trade-offs

### Risk 1：`HTTPException.detail` 改放 dict 可能破壞既有前端

既有 endpoint（如 `/shows` 409、`/rss-preview` 422）回的 `detail` 是字串，前端 QueryPage 用 `await res.text()` 處理。改 dict 後若前端沒同步改 → 顯示 `[object Object]`。

**緩解**：`formatError` 對 string detail 有 fallback（第 5 點程式碼第 12 行）；本次只改 QueryPage 採用 `formatError`，其他頁面繼續用 `res.text()` 仍能讀到 string detail（因為其他 endpoint 還沒改回 dict）。**只有 query.py 與 shows.create_show 切換到 dict detail**，影響範圍可控。

### Risk 2：global handler 吃掉所有例外可能掩蓋 bug

`@app.exception_handler(Exception)` 太寬，可能讓開發期 bug 變成靜默 500。

**緩解**：handler 內 `logger.exception(...)` 印 stack trace 到 backend log；prod 出現 `internal_error` 仍能在 Zeabur log 看到完整 traceback。

### Risk 3：Pydantic ValidationError 互動

FastAPI 內建 `RequestValidationError` handler，會被本 global handler 蓋掉嗎？

**不會**：FastAPI 內建 handler 優先（`app.exception_handlers` 已註冊 `RequestValidationError` / `HTTPException`）；本 handler 只接 `Exception`，且不會搶優先權。pytest 加 case 驗證。

### Risk 4：i18n map key 漏寫

後端新增 error_code 但前端 ERROR_MESSAGES 沒對應 → 顯示英文 fallback 而非中文。

**緩解**：後端 `error_code` 加常數模組（如 `app/schemas/errors.py:ErrorCode` enum），前端 i18n map 註解列出所有 key 供對照；pytest 確保所有 raise 點都使用常數而非 magic string。

### Trade-off：error_code 雙層 vs 單層

考慮過讓 `api_health.classify_error` 直接當 error_code（六分類），但 health tracker 的目的是 dashboard 統計、與 HTTP 回應的精細度需求不同（health 不分 quota/rate_limit；HTTP 對使用者要分）。維持兩套對應，不強行統一。
