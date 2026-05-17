## Why

2026-05-09 一天在 Zeabur AI Hub 上燒掉 $35 沒人發現，且 5/10 budget exceeded 卡 backfill 10 hr 沒告警。Zeabur AI Hub 跟 OpenAI 兩個 provider 都有 web 後台跟 CLI 拿用量資料，但**沒整合進 admin UI**，user 必須手動跑 CLI 或登入兩個外部後台才看得到。Embedding 走 OpenAI direct、answer/topic 走 AI Hub，兩個 spend 來源拆開無法互相對照。未來若加 DeepGram / Anthropic direct 等 provider，每加一個都要重做一次儀表板很煩。本 change 一次設計多 provider 用量觀測 + 閾值告警，不做自動充值（user 偏好手動充值）。

## What Changes

- 新增 `provider_usage_snapshot` 表記錄每日每 provider 每模型 spend（generic schema 可容納未來新 provider）
- 新增 Beat 每 1 hr 拉用量寫表 task，Zeabur AI Hub 走 `zeabur ai-hub usage` CLI / OpenAI 走 `https://api.openai.com/v1/organization/costs` 端點
- admin 設定頁加新 tab「服務用量」，列每 provider 30 天累積 + 當月 spend + 預設 budget bar chart
- 累積 > budget × 0.8 → 頂部 yellow banner；> budget × 0.95 → red banner + Beat 寄 ZSend 告警（每閾值 1 次/天）
- **不做** auto-recharge button — user 偏好自己處理充值
- provider abstraction：新增 `app/services/provider_usage/` 套件，各 provider 一個 `<provider>_adapter.py` 定義 `fetch_daily_usage() -> list[UsageSnapshot]`，加新 provider 只需要新一個 adapter + 註冊
- v1 adapter：Zeabur AI Hub + OpenAI direct，預留 stub for future（DeepGram / Anthropic direct / Azure direct etc）

## Non-Goals

- 不做 auto-recharge / billing 自動扣款（user 偏好手動）
- 不做 cost forecast / 「按目前速度當月會花多少」預測（v2）
- 不做 per-task / per-episode 細粒度 cost attribution（屬 R1.3 Langfuse 範疇）
- 不引入 chart library（Chart.js / Recharts）— v1 用 SVG inline rect bar 自繪，避免 CDN 體積
- 不暴露用量 API 給非 admin 使用者（admin role gate）
- 不寫真錢 transaction 紀錄（這 change 只觀測，充值仍由 user 在 Zeabur / OpenAI 後台處理）
- 不做 provider 之間自動 spend 平衡（譬如 OpenAI 便宜就自動切過去）— 屬 F2 fallback chain 範疇

## Capabilities

### New Capabilities

- `provider-usage-monitoring`: 多 provider 用量資料抽 + 持久化 + 閾值告警 + admin UI 視覺化

### Modified Capabilities

（無）

## Impact

- Affected specs: `provider-usage-monitoring`
- Affected code:
  - New:
    - `backend/alembic/versions/<ts>_add_provider_usage_snapshot.py`
    - `backend/app/models/provider_usage_snapshot.py`
    - `backend/app/services/provider_usage/__init__.py`（abstraction）
    - `backend/app/services/provider_usage/zeabur_aihub_adapter.py`
    - `backend/app/services/provider_usage/openai_adapter.py`
    - `backend/app/workers/usage_collector.py`（Beat task 每 1 hr 拉資料）
    - `backend/app/workers/usage_alert.py`（Beat task 每天 09:00 台北評估閾值告警）
    - `backend/app/api/admin_provider_usage.py`（admin REST：daily list / monthly summary / current month spend）
    - `backend/tests/test_provider_usage_adapters.py`
    - `backend/tests/test_usage_collector.py`
    - `backend/tests/test_usage_alert.py`
    - `backend/tests/test_admin_provider_usage_api.py`
    - `src/AdminPage.jsx` 內新 ProviderUsageTab 區塊（自繪 SVG bar chart）
  - Modified:
    - `backend/app/workers/celery_app.py`（beat_schedule 加 usage-collector + usage-alert）
    - `backend/app/services/zsend.py`（加 send_usage_threshold_alert helper）
    - `src/AdminPage.jsx` 加 tab 路由 `page='admin-provider-usage'`
    - `src/Shared.jsx` admin nav 加「服務用量」連結
