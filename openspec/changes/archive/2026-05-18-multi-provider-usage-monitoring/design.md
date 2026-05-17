## Context

PodcastRAG 目前用兩個 LLM provider：(1) Zeabur AI Hub（answer / rewrite / topic_seg / summary 走 hnd1.aihub.zeabur.ai/v1，後面是 litellm + Azure OpenAI / Google / Anthropic 等多家）(2) OpenAI direct（embedding / Whisper transcription 走 api.openai.com/v1）。各自的用量資料管道不同：

- Zeabur AI Hub：CLI `zeabur ai-hub usage --json` 回 30 天 daily breakdown（含 model 維度）
- OpenAI direct：API `https://api.openai.com/v1/organization/costs?start_time=...`（需要 org admin key），回每日 spend，可附 `group_by=line_item` 拿 model 維度
- 未來新 provider（DeepGram / Anthropic direct / Azure direct etc）：各家 usage API 不同

5/9 燒 $35 + 5/10 budget exceeded 兩起事件直接動機。User 偏好手動充值，所以本 change 不做 auto-recharge — 只觀測 + 寄信告警讓 user 知道何時該充。

相關但無依賴的 changes：F2 task-failure-monitoring-and-circuit-breaker 處理「provider 失敗」，本 change 處理「provider 用量」— 兩件事正交（用量正常但失敗仍可能 / 用量爆但 task 仍可能成功直到 budget hit）。

## Goals / Non-Goals

**Goals:**

- Admin 一個地方看到所有 LLM / 轉錄 provider 的當月 spend
- 預設 budget × 0.8 → yellow banner，× 0.95 → red banner + ZSend 寄信
- 加新 provider 只需要 1 個 adapter 檔 + 1 行註冊，不動 UI / DB schema
- 用量資料持久化（重啟不丟，可看 30 天歷史）
- 不引入新 chart library / CDN dependency

**Non-Goals:**

- 不做 auto-recharge / billing 自動扣款（user 偏好手動）
- 不做 cost forecast / 未來預測 / 推估剩餘可用天數（v2 polish）
- 不做 per-task / per-episode cost attribution（屬 R1.3 Langfuse）
- 不做 cost optimisation 建議（譬如「Gemini 比 gpt-4o 便宜 30% 建議切換」）
- 不做 manual 重新拉用量資料的 admin button（v1 靠 Beat 自動每 1 hr，需要立即更新去後台看）
- 不做 spend 歷史 export CSV（v2 polish）

## Decisions

### Decision: provider_usage_snapshot 表用 generic schema 不依賴特定 provider

**選擇**：表只欄 `provider, model, date, spend_usd, raw_payload jsonb, fetched_at`。新 provider 加 row 不改 schema。

**理由**：

- adapter 各自把 provider 原生 API 回應 normalise 成這個 shape
- raw_payload 留原始 JSON 方便事後 debug / 加新欄位不需 migration
- 簡單聚合：`SELECT provider, SUM(spend_usd) FROM provider_usage_snapshot WHERE date >= ... GROUP BY provider`

**替代**：每 provider 一張表 — 過度設計、加新 provider 要 alembic migration、聚合要 UNION 多張表。

### Decision: Adapter 介面定義為單一 fetch_daily_usage 函式

**選擇**：每個 `<provider>_adapter.py` 只暴露：

```python
async def fetch_daily_usage(start: date, end: date) -> list[UsageSnapshot]:
    """Returns list of (date, model, spend_usd, raw_payload) for given range."""
```

`UsageSnapshot` 是 dataclass `(provider, model, date, spend_usd, raw_payload)`。註冊在 `provider_usage/__init__.py` 的 `ADAPTERS` dict（key=provider id）。

**理由**：

- 介面最小，每個 adapter 自己處理 auth / rate limit / pagination
- 單一函式單一責任，好測試
- 未來加 streaming / webhook 模式時，可以加 `subscribe_realtime()` 不破壞既有

**替代**：類別 + 多 method（`auth() / fetch_models() / fetch_per_model()`）— 過度抽象、目前需求單一。

### Decision: usage_collector Beat task 每 1 hr 拉一次

**選擇**：Beat schedule 加 `usage-collector`，cron `0 * * * *`，每小時整點跑。每次拉「今天 + 昨天」（昨天為了補完整跨日）。

**理由**：

- AI Hub usage CLI / OpenAI usage API 都是 near-realtime（幾分鐘延遲），不需更高頻
- 1 hr 解析度對「budget 還剩多少」決策夠用
- 整點跑方便 admin 預期下次更新時間
- 拉「今天 + 昨天」覆蓋跨日 race

**替代**：每 5 min — 過頻 + Zeabur CLI 不適合高頻呼叫。每天 1 次 — 太疏，半天才察覺異常。

### Decision: 閾值告警 80% / 95% 雙級 + per-day 去重

**選擇**：每天 09:00 台北 跑 `usage-alert` Beat task，計算每 provider 當月累積 vs `provider_budget_usd_monthly` config（v1 hardcoded：aihub=$60, openai=$30，可後續加 admin UI）：

- 累積 / budget >= 0.95 → red 等級告警
- 累積 / budget >= 0.80 → yellow 等級告警（但只在 < 0.95 時寄）
- 同一 provider 同一天最多寄 1 封 yellow + 1 封 red（透過 `usage_alert_log` 表去重，類似 F2 alerted_at 模式）

**理由**：

- 雙級給 user 早期警告（80% 還有時間決定是否充值）+ 緊急警告（95% 該立刻動）
- per-day 去重避免信箱被洗
- 09:00 台北 跑 = user 起床前後

**替代**：每小時即時偵測 → 信箱爆。單級 90% → 不夠早警示。

### Decision: Admin UI v1 用 SVG inline 自繪 bar chart

**選擇**：`src/AdminPage.jsx` 內 ProviderUsageTab 自寫 SVG `<rect>` 畫 daily bar chart + monthly summary cards。**不裝 Chart.js / Recharts / D3**。

**理由**：

- 30 天 × 3 provider = 90 個 bar，SVG 完全 cover
- 不增加 CDN bundle 體積（PodcastRAG 走 Babel CDN 模式）
- 互動需求極簡（hover tooltip 顯示日期 + spend）
- 未來真有複雜需求再裝 lib

**替代**：Chart.js — 體積 + CDN 一個 dependency。HTML table 純文字 — 不夠視覺化。

### Decision: OpenAI direct 用 organization/costs API + 新增 OPENAI_ORG_ADMIN_KEY env

**選擇**：OpenAI usage 走 `GET https://api.openai.com/v1/organization/costs` 端點，需要 organization admin key（不是一般 API key）。env 新增 `OPENAI_ORG_ADMIN_KEY`，user 在 OpenAI 後台 https://platform.openai.com/settings/organization/admin-keys 產一把專用 key。如果未設，OpenAI adapter 跳過該日資料寫入並 log warning（不報錯，service 仍能跑）。

**理由**：

- 一般 API key 沒有讀 usage 權限（OpenAI 安全設計）
- admin key 可 scope 到唯讀，洩漏風險可控
- 跳過模式讓 v1 可漸進部署（先有 AI Hub 也可上線）

**替代**：用 dashboard scraping — 脆弱 + 違反 ToS。

## Risks / Trade-offs

- **Risk: Zeabur CLI exec 在 worker container 失敗（未裝 zeabur CLI）** → Mitigation: Zeabur AI Hub 也提供 HTTP API（Bearer auth），用 HTTP 直接打不依賴 CLI（adapter 內 implementation detail）
- **Risk: OpenAI org admin key 不在 .env 模板** → Mitigation: 文件 + onboarding 加說明；未設時 graceful degrade（log warning 不 crash）
- **Risk: 每 1 hr 拉資料但 Zeabur AI Hub 內部更新有延遲** → Mitigation: 每次拉「今天 + 昨天」覆蓋；告警邏輯接受 1-2 hr 落後是 acceptable
- **Risk: provider_budget_usd_monthly hardcoded user 改不到** → Mitigation: v1 寫死可接受（user 自己改 config 加註解），v2 加 admin UI 設定（屬未來 polish change）
- **Trade-off: 不做 forecast / cost optimisation** → 接受 v1 只觀測 + 告警

## Migration Plan

1. **Stage A — DB + adapter**（無對外行為改變）
   - alembic migration 加 provider_usage_snapshot + usage_alert_log 兩表
   - 寫 abstraction + 兩個 adapter（aihub / openai）
   - unit test
2. **Stage B — Beat tasks**
   - usage_collector + usage_alert 加進 beat_schedule
   - ZSend helper
3. **Stage C — Admin REST + UI**
   - admin_provider_usage.py REST endpoints
   - ProviderUsageTab + 自繪 SVG chart
4. **Stage D — Deploy + smoke**
   - Push → 4 service rebuild redeploy
   - 等 1 hr 收一次資料；admin 開頁確認資料對得上 Zeabur / OpenAI 後台
   - 故意把 budget config 設低觸發 yellow banner 驗證告警

**Rollback**：env 砍 OPENAI_ORG_ADMIN_KEY + alembic downgrade（兩表 drop，影響 0）

## Open Questions

- `provider_budget_usd_monthly` 預設值多少？AI Hub 目前 $60，OpenAI 之前估計 ~$10/月（embedding + transcription），暫定 aihub=$80, openai=$30
- usage_collector 失敗時要不要寄信？傾向不寄（Beat 自己 retry，連續失敗才寄 — 屬 F2 範疇）
- AI Hub 走 CLI 還是 HTTP？傾向 HTTP（更穩、不依賴 worker container 裝 CLI）
