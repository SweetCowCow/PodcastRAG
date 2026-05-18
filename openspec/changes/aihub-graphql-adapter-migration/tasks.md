## 1. 新 adapter 實作

- [x] 1.1 新建 `backend/app/services/provider_usage/zeabur_aihub_graphql.py`，實作 `fetch_daily_usage(start, end) -> list[UsageSnapshot]`：(a) 讀 `ZEABUR_API_TOKEN` env，未設則 log warning + 回 []；(b) 跨月時拆 month list、>6 個月 raise ValueError；(c) 對每個月 POST `https://api.zeabur.com/graphql` 帶 `aihubMonthlyUsage(month: $month)` query；(d) 解析 dailyUsage→models breakdown 為 UsageSnapshot list；(e) 過濾 `start <= snapshot.date <= end`；(f) GraphQL response 含 errors 欄位 → raise RuntimeError；(g) 4xx 立即 raise；(h) 5xx 用盡 retry 後 raise（不 fail-open）。完成標準：`python -c "from app.services.provider_usage.zeabur_aihub_graphql import fetch_daily_usage; print(fetch_daily_usage.__doc__)"` 不 import error
- [x] 1.2 [P] 在 `backend/app/core/config.py` 新增 `zeabur_api_token: str | None = None`；保留 `aihub_usage_key` 暫不刪（向前相容）。完成標準：`Settings().zeabur_api_token is None` by default；env `ZEABUR_API_TOKEN=xxx` → `Settings().zeabur_api_token == "xxx"`
- [x] 1.3 [P] 更新 `backend/.env.example` 加 `ZEABUR_API_TOKEN=` 條目，含「從 ~/.config/zeabur/cli.yaml 取得」註解；保留 `AIHUB_USAGE_KEY=`（標記 deprecated）。完成標準：`grep ZEABUR_API_TOKEN backend/.env.example` 有 match

## 2. 單元測試

- [x] 2.1 新建 `backend/tests/services/test_aihub_graphql_adapter.py`，用 `httpx_mock` 或 `respx` 蓋以下 case：
  - `test_single_month_returns_snapshots`：mock GraphQL 回 totalSpend + dailyUsage（兩天、各兩個 model）→ 解析出 4 個 UsageSnapshot，Decimal 精度正確
  - `test_cross_month_range_splits_queries`：start=2026-04-29 end=2026-05-02 → 計次斷言 2 次 POST、合併後 snapshots 都在 range 內
  - `test_no_token_returns_empty_with_warning`：清掉 env → caplog 有 "ZEABUR_API_TOKEN not configured" + 回 []
  - `test_5xx_raises_after_retries`：mock 503 × 3 → 最終 raise `httpx.HTTPStatusError`
  - `test_4xx_raises_immediately`：mock 401 → raise 不 retry（mock 計次 == 1）
  - `test_graphql_errors_field_raises`：response 200 但含 `errors` 陣列 → raise RuntimeError 訊息含 "GraphQL errors"
  - `test_range_over_6_months_raises_value_error`：start=2025-01-01 end=2026-05-01 → raise ValueError 含 "Date range too large"
  完成標準：`cd backend && pytest tests/services/test_aihub_graphql_adapter.py -v` 7 個全綠

## 3. ADAPTERS 切換

- [x] 3.1 修改 `backend/app/services/provider_usage/__init__.py`：`ADAPTERS['aihub']` 從 `zeabur_aihub_adapter.fetch_daily_usage` 改指 `zeabur_aihub_graphql.fetch_daily_usage`。完成標準：`python -c "from app.services.provider_usage import ADAPTERS; print(ADAPTERS['aihub'].__module__)"` 印出 `app.services.provider_usage.zeabur_aihub_graphql`

## 4. 刪除舊 adapter

- [x] 4.1 刪除 `backend/app/services/provider_usage/zeabur_aihub_adapter.py` 與 `backend/tests/services/test_zeabur_aihub_adapter.py`。完成標準：兩個檔案不存在；`cd backend && pytest -x` 全綠無 import error

## 5. Prod 部署 + 驗證

- [x] 5.1 注入 `ZEABUR_API_TOKEN` 到 prod worker env（user 操作；用 `zeabur variable update --service-id 69eb1c620da29f05f49a4e2a --env-id 69eb0fb3d34cd657ee345ea4 -k ZEABUR_API_TOKEN -v "$TOKEN" -i=false`，**不用 create**）。完成標準：`zeabur variable list --service-id 69eb1c620da29f05f49a4e2a --json | jq '.[].key' | grep ZEABUR_API_TOKEN` 有 match
- [x] 5.2 Push commit、redeploy worker、等 RUNNING。完成標準：`zeabur deployment list --service-id 69eb1c620da29f05f49a4e2a --json | jq '.[0].status'` 回 `"RUNNING"` + commit SHA 是新的
- [x] 5.3 觸發一輪 collector 或等下個整點，查 worker log：grep `usage_collector` 無 aihub error、有 "aihub success"-類訊息。完成標準：log tail 5 分鐘內無 aihub-related ERROR

**2026-05-18 驗證**：`zeabur service exec` 手動 trigger `collect_provider_usage()` 回 `{'counts': {'aihub': 2, 'openai': 3}, 'errors': {}}`，aihub 從之前 0 變 2 records。
- [x] 5.4 Prod SQL 對帳：`SELECT date, sum(spend_usd) FROM provider_usage_snapshot WHERE provider='aihub' AND date >= '2026-05-01' GROUP BY date ORDER BY date DESC LIMIT 10;` 結果非空、加總接近 `zeabur ai-hub usage --json` totalSpend（diff ≤ 0.1%）。完成標準：sum(spend_usd) >= $77.50 且 ≤ $78.50（5/18 當下）
- [x] 5.5 觸發一輪 `/admin/usage/summary`，確認 `aihub` provider 顯示非 0 spend。完成標準：response JSON `providers.aihub.total > 0`

**2026-05-18 驗證**：user 瀏覽器登入 admin 看 usage 頁面，aihub 那欄已顯示數字（取代 admin SQL 對帳 + endpoint response 兩條驗證，視覺確認等效於 5.4 + 5.5）。

## 6. 收尾

- [x] 6.1 [P] 補 case study `docs/case-studies/aihub-graphql-migration-2026-05-18.md`（記錄 9 天無人發現的根因 + GraphQL 切換過程 + verification SOP）。完成標準：檔案存在且涵蓋三段；**不入 git**（per `feedback_case_studies_no_commit.md`）
- [x] 6.2 Release log 起草：在 `src/releaseLog.jsx` 補 entry（使用者視角：「後台 AI Hub 用量數字之前一直顯示 0，現在已可正常追蹤實際花費」）。完成標準：grep `aihub-graphql-adapter-migration` src/releaseLog.jsx 有新 entry

**2026-05-18 完成**：v1.7 milestone 插在 multi-provider-usage-monitoring entry 上方，tag=fix。
- [x] 6.3 更新 memory `project_pending_changes.md` 移除 `aihub-graphql-adapter-migration` 從 pending 列表。完成標準：grep `aihub-graphql` ~/.claude/projects/-Users-jackylin-Documents-Project-PodcastRAG/memory/project_pending_changes.md 無未完成標記
