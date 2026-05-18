## Summary

把 AI Hub usage adapter 從猜測的 REST endpoint `https://aihub.zeabur.app/v1/usage`（不存在）改成 Zeabur 官方 GraphQL `https://api.zeabur.com/graphql` 的 `aihubMonthlyUsage` query，修復 2026-05-09 起 9 天無人發現的 aihub usage 全 0 問題。

## Motivation

`backend/app/services/provider_usage/zeabur_aihub_adapter.py` 走的 `aihub.zeabur.app/v1/usage` 是 2026-05-09 寫 multi-provider-usage-monitoring change 時憑感覺猜的 URL，事實上根本不存在。9 天內 `provider_usage_snapshot` 表 aihub provider 沒有一筆 row 寫入、`/admin/usage/summary` 永遠回 `aihub: 0`、預算告警 `aihub: $0/$80 ratio 0` — 全程無人發現，直到 2026-05-18 凌晨手動跑 `zeabur ai-hub status` 才知道 AI Hub 實際累積 $77.50。

當前 5/18 凌晨的 hotfix `03d88c4` 把 5xx/timeout 改 fail-open（不 raise）以避免 collector 被 502 噴爆 log，但這只解決「噪音」、沒解決「資料」。要拿到真實 aihub usage，必須換到官方支援的查詢路徑。

memory `feedback_verify_external_endpoint_first.md` 已記錄這次教訓（寫 adapter 前必須 curl 驗 endpoint），本 change 是落實修補。

## Proposed Solution

1. 新建 `backend/app/services/provider_usage/zeabur_aihub_graphql.py` 取代既有 REST adapter
   - GraphQL endpoint: `https://api.zeabur.com/graphql`
   - Query: `aihubMonthlyUsage(month: String)` 回 `totalSpend`、`dailyUsage[{date, spend, models[{model, cost}]}]`、`modelsCost[]`
   - Auth: `ZEABUR_API_TOKEN` env (Bearer token，從 Zeabur CLI auth flow 取得)
   - Date range 處理：GraphQL 是 monthly 粒度，adapter 接 `(start, end)` 後拆成 month list 跑多次 query、過濾出落在 range 內的 `dailyUsage[]` 條目
2. 將 `ADAPTERS['aihub']` 指向新模組
3. 移除 fail-open patch（GraphQL endpoint 由 Zeabur 維護，比猜測 URL 穩；保留 4xx raise / 5xx 觀察）
4. 刪除 `zeabur_aihub_adapter.py`（舊 REST adapter）與相關測試
5. 補上 case study `docs/case-studies/aihub-graphql-migration-2026-05-18.md`（不入 commit per case-studies rule）

## Non-Goals

- 不寫第 4 個 provider adapter（如 Anthropic / Google）
- 不改 collector 排程、不動 `provider_usage_snapshot` 表 schema
- 不重做 OpenAI adapter（既有運作正常）
- 不解決 GraphQL endpoint 全停的情境（信任 Zeabur 平台 SLA，5xx 仍 raise 讓 collector log 告警）
- 不引入 GraphQL client library（如 gql）— 用 httpx 直送 POST 已足夠
- 不寫 admin UI provider switch（仍是固定 ADAPTERS dict）

## Alternatives Considered

- **保留 REST adapter + 找對的 endpoint**：Zeabur 沒公開 REST endpoint 給 AI Hub usage；CLI 內部也用 GraphQL。猜下一個 URL 不會比第一個準。
- **Container 裝 zeabur CLI 跑 subprocess `zeabur ai-hub usage --json`**：增加 image size + subprocess 在 PaaS 易掛 + CLI version drift 風險。GraphQL 直打更輕。
- **接 Zeabur 推送 webhook（如果有）**：Zeabur 目前無 usage webhook 公開支援，等於再猜一次。
- **用 GraphQL client library（gql / strawberry-client）**：query 結構固定且小，httpx + JSON 即可，避免新依賴。

## Impact

- Affected specs: `provider-usage-monitoring`（modify Adapter interface for provider usage 的 AI Hub scenario）
- Affected code:
  - New:
    - `backend/app/services/provider_usage/zeabur_aihub_graphql.py`
    - `backend/tests/services/test_aihub_graphql_adapter.py`
  - Modified:
    - `backend/app/services/provider_usage/__init__.py`（ADAPTERS 改指新模組）
    - `backend/app/core/config.py`（移除 `aihub_usage_key`，新增 `zeabur_api_token`）
    - `backend/.env.example`
  - Removed:
    - `backend/app/services/provider_usage/zeabur_aihub_adapter.py`
    - `backend/tests/services/test_zeabur_aihub_adapter.py`（舊 REST 測試）
- 環境變數：prod worker 需新增 `ZEABUR_API_TOKEN`（apply 階段用 `zeabur variable update` 注入，避免 `create` dump env 問題），同時寫 `backend/.env` 供本機測試
- 無 DB schema 變更；無 migration
