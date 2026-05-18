## Context

`backend/app/services/provider_usage/zeabur_aihub_adapter.py` 走 `https://aihub.zeabur.app/v1/usage` — 該 endpoint 不存在（2026-05-09 寫 multi-provider-usage-monitoring change 時憑感覺猜的 URL），導致 collector 9 天每小時都打到 5xx、aihub provider 在 `provider_usage_snapshot` 表內毫無資料。5/18 凌晨 hotfix `03d88c4` 把 5xx/timeout 改 fail-open（不 raise）以避免 log 噪音，但這只是壓住症狀。

Zeabur 官方 GraphQL endpoint `https://api.zeabur.com/graphql` 是 CLI (`zeabur ai-hub usage`) 與 ai-sdk 內部使用的真正資料來源，schema 公開於 `zeabur/ai-sdk` repo。本機 curl 已驗證 `totalSpend=$77.54` 與 `zeabur ai-hub status` 顯示的 $77.50 完全吻合，endpoint + auth + query schema 三項都通。

## Goals / Non-Goals

**Goals**
- aihub 真正寫進 `provider_usage_snapshot` 表，與實際 spend 一致（diff ≤ 0.1%）
- 不增加 image size（無 zeabur CLI binary 依賴）
- Token rotation 流程清晰（env 注入 + 不寫 source code）
- 5xx 重新變成 raise（恢復 fail-loud 行為，因為 GraphQL endpoint 比猜測 URL 穩）

**Non-Goals**
- 寫新 provider adapter（範圍限定 aihub）
- 動 `provider_usage_snapshot` schema
- 引入 GraphQL client library（用 httpx）
- 完整覆蓋 AI Hub 所有 GraphQL operations（只取 monthly usage）
- Token 自動 rotation（手動透過 `zeabur variable update` 注入即可）

## Decisions

- **改用 `aihubMonthlyUsage` query 而非 `aihubTenant`**：前者回 dailyUsage + per-model breakdown，符合 `UsageSnapshot(provider, model, date, spend_usd)` 結構；後者只回 balance + per-key cost（沒日期、沒模型 breakdown）。
- **GraphQL 是 monthly 粒度，adapter 內部拆 month**：fetch_daily_usage(start, end) 接到 cross-month range 時拆成多次 query（如 2026-04-29 ~ 2026-05-02 → 跑 `month=2026-04` + `month=2026-05`），合併後過濾 `start <= d <= end` 的 dailyUsage 條目。MAX_MONTHS = 6（避免錯誤 range 把 query 數炸開）。
- **每月一個 GraphQL request、不嘗試精確「只查 N 天」**：GraphQL 沒有日期 filter，硬要拉每日要打 N 次（一日一次 month query）反而更慢；一個月份 query 拿回所有日比較划算。
- **httpx + JSON POST，不引入 gql client**：query string 固定一行、無 fragment、無 subscription，httpx 一個 POST 即可，避免新依賴與 typing 複雜性。
- **5xx 改回 raise**：fail-open 是 hotfix；新 adapter 信任 Zeabur SLA，5xx 觸發 collector log error 讓人看見比沉默更好。4xx 一律 raise（misconfig / token 錯）。
- **`ZEABUR_API_TOKEN` 用 `zeabur variable update`（非 create）**：依 memory `feedback_zeabur_variable_create_dumps_env.md`，create 即使 `-i=false` 仍 dump 整份 env。update 安全。
- **保留舊 `AIHUB_USAGE_KEY` env 不刪除**：避免破壞既有 prod 部署，但程式碼不再讀（兼容到下次 env 大掃除）。
- **超時策略**：connect 10s / read 30s / total 45s / 3 attempts exponential backoff（沿用既有 adapter 設定），單次 query 是 monthly aggregate 不會慢。

## Implementation Contract

**Observable behaviors**

1. `fetch_daily_usage(start: date, end: date)` 接收 date range（同月 / 跨月皆可），回 `list[UsageSnapshot]`，每筆對應 `(aihub, model, date, spend_usd, raw_payload)`。
2. `ZEABUR_API_TOKEN` 未設時：log WARNING `"ZEABUR_API_TOKEN not configured, skipping aihub usage fetch"` + 回 `[]`（沿用既有 contract，符合 spec 第三條 scenario）。
3. 4xx response → raise `httpx.HTTPStatusError`（collector 會記入 errors dict）。
4. 5xx response 用盡 3 retries → raise（**不再 fail-open**）。
5. GraphQL response 含 `errors` 陣列 → raise `RuntimeError(f"GraphQL errors: {errors}")`。
6. Date range 跨月：adapter 自動拆 month 跑多次 query，合併後過濾。
7. Date range 跨 6 月以上 → raise `ValueError("Date range too large: max 6 months")`。
8. `ADAPTERS['aihub']` 在 `__init__.py` 切換為新模組 import。
9. 舊檔案刪除：`zeabur_aihub_adapter.py` 與 `test_zeabur_aihub_adapter.py`。

**Data shape**

- GraphQL request body: `{"query": "<above>", "variables": {"month": "2026-05"}}`
- GraphQL response: `{"data": {"aihubMonthlyUsage": {"totalSpend": float, "dailyUsage": [{"date": "YYYY-MM-DD", "spend": float, "models": [{"model": str, "cost": float}]}], "modelsCost": [...]}}}`
- 轉成 UsageSnapshot：對每個 `dailyUsage[i]`，每個 `models[j]` 產一筆 `UsageSnapshot(provider="aihub", model=models[j].model, date=parsed_date, spend_usd=Decimal(str(models[j].cost)), raw_payload={"date": ..., "model": ..., "spend": ...})`。

**Acceptance criteria**

- `backend/tests/services/test_aihub_graphql_adapter.py` 涵蓋：
  - `test_single_month_returns_snapshots`：mock GraphQL 回固定 payload → 解析正確、Decimal 精度正確
  - `test_cross_month_range_splits_queries`：start=2026-04-29 end=2026-05-02 → 觸發 2 個 GraphQL POST（用 httpx mock 計次）
  - `test_no_token_returns_empty_with_warning`：env 未設 → `[]` + log WARNING
  - `test_5xx_raises_after_retries`：mock 5xx 3 次 → 最終 raise（**新行為**）
  - `test_4xx_raises_immediately`：mock 401 → raise，無 retry
  - `test_graphql_errors_field_raises`：response 含 errors → raise RuntimeError
  - `test_range_over_6_months_raises_value_error`
- 手動 prod 驗證（apply 階段）：
  - `zeabur variable update` 注入 `ZEABUR_API_TOKEN` 到 worker
  - Redeploy worker、查 collector log 含 aihub success
  - SQL: `SELECT date, sum(spend_usd) FROM provider_usage_snapshot WHERE provider='aihub' GROUP BY date ORDER BY date DESC LIMIT 7;` → 數字非 0 且接近 `zeabur ai-hub usage --json` totalSpend

**Scope boundaries**

- 範圍內：新 adapter 模組 + 7 個單元測試 + ADAPTERS 切換 + config env 變更 + .env.example 更新 + 舊檔案刪除 + prod env 注入指示 + manual prod verify steps
- 範圍外：其他 provider adapter、collector 排程、UI、admin endpoint、預算告警邏輯、DB schema

## Risks / Trade-offs

- **GraphQL schema drift**（Zeabur 改 query 結構） → 抓 ai-sdk repo 對 schema；每月 prod verify SQL 數字 vs CLI 對帳一次當 canary
- **`ZEABUR_API_TOKEN` 洩漏** → token 只在 worker env，不入 git；rotation 流程：`zeabur auth logout && zeabur auth login` 後重抓 cli.yaml token 並 `zeabur variable update`
- **5xx 重新 raise 可能讓 collector log 變吵** → 信任 Zeabur SLA；真的長期 5xx 時人為介入比 silent drop 安全
- **Token 過期未察覺** → 401 raise → collector errors dict + log → admin email digest（multi-provider-usage-monitoring 既有機制）會通知

## Migration Plan

1. 部署新 adapter（先不切 ADAPTERS dict，並存）
2. 寫單元測試全綠
3. 在 dev 環境設 `ZEABUR_API_TOKEN`、手動跑 `await fetch_daily_usage(date(2026,5,1), date(2026,5,18))` 對帳 totalSpend
4. 切 ADAPTERS dict 指向新模組，commit + push
5. `zeabur variable update` 注入 prod token、redeploy worker
6. 觀察 collector 第一輪跑（next hour），SQL 對帳
7. 刪舊 adapter + 測試
8. Rollback：revert ADAPTERS dict commit + `zeabur variable delete ZEABUR_API_TOKEN`（worker 仍可跑、aihub 回 0 fail-open 已不在）
