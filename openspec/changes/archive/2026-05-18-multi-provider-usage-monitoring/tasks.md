## 1. DB schema

- [x] 1.1 寫 alembic migration 加 `provider_usage_snapshot`（id / provider / model / date / spend_usd / raw_payload / fetched_at + unique (provider, model, date)）跟 `usage_alert_log`（provider / severity / alerted_date PK），含對應 SQLAlchemy model（落實 Decision: provider_usage_snapshot 表用 generic schema 不依賴特定 provider + Requirement: Provider usage snapshot table）

## 2. Adapter abstraction + 兩個實作

- [x] 2.1 寫 `backend/app/services/provider_usage/__init__.py` 暴露 `UsageSnapshot` dataclass + `ADAPTERS` dict + 註冊機制（落實 Decision: Adapter 介面定義為單一 fetch_daily_usage 函式 + Requirement: Adapter interface for provider usage）
- [x] 2.2 寫 `zeabur_aihub_adapter.py`：用 HTTP（不依賴 zeabur CLI 是否裝）打 AI Hub usage endpoint，需要 Bearer auth；normalise 回 list[UsageSnapshot]（落實 Decision: AI Hub 走 CLI 還是 HTTP）
- [x] 2.3 寫 `openai_adapter.py`：用 `OPENAI_ORG_ADMIN_KEY` env 打 `https://api.openai.com/v1/organization/costs`，未設 env 時 log warning 回 `[]`（落實 Decision: OpenAI direct 用 organization/costs API + 新增 OPENAI_ORG_ADMIN_KEY env + Requirement: Adapter interface scenario "without admin key gracefully returns empty"）
- [x] 2.4 寫 `backend/tests/test_provider_usage_adapters.py`：mock httpx response，驗 aihub / openai adapter 各回正確 UsageSnapshot；驗 openai 沒 env 時回 []

## 3. Beat tasks（usage_collector + usage_alert）

- [x] 3.1 寫 `backend/app/workers/usage_collector.py` Beat task，每 1 hr 整點跑：iterate `ADAPTERS`、呼叫 `fetch_daily_usage(yesterday, today)`、upsert 進 provider_usage_snapshot；per-adapter 失敗隔離（落實 Decision: usage_collector Beat task 每 1 hr 拉一次 + Requirement: Hourly usage collector beat task）
- [x] 3.2 寫 `backend/app/workers/usage_alert.py` Beat task，每天 09:00 台北 跑：算當月累積 vs `provider_budget_usd_monthly` config、80%/95% 雙級判斷、per-day 去重、寄 ZSend（落實 Decision: 閾值告警 80% / 95% 雙級 + per-day 去重 + Requirement: Daily usage threshold alert beat task）
- [x] 3.3 在 `celery_app.py` beat_schedule 加 `usage-collector`（cron `0 * * * *`）跟 `usage-alert`（cron `0 1 * * *` UTC）兩個 entry
- [x] 3.4 在 `backend/app/services/zsend.py` 新增 `send_usage_threshold_alert(provider, severity, accumulated, budget, ratio, top_models, taipei_date)` helper，純文字繁中
- [x] 3.5 在 `backend/app/core/config.py` 加 `provider_budget_usd_monthly: dict` config（v1 hardcoded：aihub=80, openai=30）+ `openai_org_admin_key: str | None` env
- [x] 3.6 寫 `backend/tests/test_usage_collector.py`：mock 兩個 adapter，驗 upsert 行為 + per-adapter 失敗隔離
- [x] 3.7 寫 `backend/tests/test_usage_alert.py`：覆蓋 4 個 scenario（80% triggers yellow / 95% triggers red / already-alerted no re-alert / below 80% no alert）

## 4. Admin REST

- [x] 4.1 寫 `backend/app/api/admin_provider_usage.py`：`GET /admin/provider-usage/daily?start=&end=` + `GET /admin/provider-usage/monthly`，admin role gate + CSRF（落實 Requirement: Admin REST endpoint for usage data）
- [x] 4.2 註冊 router 進 main.py
- [x] 4.3 寫 `backend/tests/test_admin_provider_usage_api.py`：覆蓋 daily / monthly 回應結構 + non-admin 403

## 5. Admin UI

- [x] 5.1 在 `src/AdminPage.jsx` 加新 `ProviderUsageTab` 元件：fetch /admin/provider-usage/monthly + daily、render summary cards + 30 天 stacked SVG bar chart（自繪 `<rect>`，不裝 chart lib）+ hover tooltip（落實 Decision: Admin UI v1 用 SVG inline 自繪 bar chart + Requirement: Admin UI shows usage chart and budget banner）
- [x] 5.2 ProviderUsageTab top 加雙 banner 邏輯（yellow >= 80% / red >= 95%），red banner 含「前往 Zeabur AI Hub」+「前往 OpenAI dashboard」外部 link（無 auto-recharge button — 落實 Non-Goal）
- [x] 5.3 自動 60s polling 重 fetch
- [x] 5.4 雙語 i18n（繁中 + 英文 key）
- [x] 5.5 在 `src/Shared.jsx` admin nav 加「服務用量」連結，加 page route `admin-provider-usage`

## 6. 部署 + smoke

- [x] 6.1 onboarding 文件補：user 要去 OpenAI 後台產 organization admin key 設進 env `OPENAI_ORG_ADMIN_KEY`；AI Hub Bearer key 用 `ZSEND_API_KEY`-style env 名 `AIHUB_USAGE_KEY`（如已有就 reuse）
- [x] 6.2 commit + push → Zeabur 4 service rebuild redeploy（main `7fcf6f8` + hotfix `03d88c4` aihub fail-open）
- [x] 6.3 prod 觸發 usage-collector → openai 寫入正常 $6.10/$30；aihub **endpoint URL 從頭猜錯**（`/v1/usage` 不存在，正解是 `api.zeabur.com/graphql` + `aihubMonthlyUsage` query），fail-open 後 collector 不再被阻塞、admin tab 可正常顯示 openai；aihub 真實接入拉到 follow-up change `aihub-graphql-adapter-migration`。詳見 `docs/case-studies/aihub-endpoint-guessed-2026-05-18.md`
- [x] 6.4 Alert pipeline 用 `evaluate_usage_thresholds()` dry-run 驗過 E2E 健康：openai $6.10/$30 ratio 0.20 未達門檻 / aihub $0/$80 未達門檻；severity null、`usage_alert_log` 0 row 符合預期；dedupe 邏輯 unit test 涵蓋
- [x] 6.5 release log v1.7 補 entry（使用者視角）
