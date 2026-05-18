## Why

2026-05-10 同日兩個沒人發現的故障：(1) EP20 transcribe 卡 9+ 小時 0 segments，沒任何告警；(2) R3.2 topic backfill enqueue 323 個 task，worker 因 deploy 落後不認得 task name → Celery silent drop 全部，DB 沒寫一筆，整個過程 zero log。背景任務缺乏觀測層 + 缺乏對外部服務失敗的保護機制 → 失敗時沒人知道、永遠失敗的 task 一直 retry 燒 LLM quota、補完 quota 後也要手動重新 enqueue 已 mark failed 的整批 task。

## What Changes

- 新增 Celery task 失敗事件記錄（task name / args / failure type / error message / timestamp）
- 新增失敗率告警：30 min 滑動窗口失敗 ≥ 3 次 → ZSend 寄信
- 把 task 錯誤分類為「暫時錯」與「永久錯」：
  - 暫時錯（network timeout, 429 rate limit, 5xx）→ 維持 retry 3 次
  - 永久錯（402 額度不足 / 401 金鑰失效 / 400 prompt 超 context / 415 大檔 / TaskNotRegistered）→ 立刻 mark failed，不 retry
- 新增 service circuit breaker：對外部 provider（OpenAI / Zeabur AI Hub / ZSend）5 min 滑動窗口內連續 3 個永久錯 → 暫停所有用該 provider 的 task；task 執行前查 circuit state，若 open 則自我 retry 5 min 後再試
- 新增自動恢復探測：每 30 min Beat tick 對 open 的 provider 試發 sentinel probe，成功 → state=closed + ZSend 通知恢復；失敗 → 維持 open
- 新增 admin 「服務狀態」UI tab：列 3 provider state + 暫停時間 + 影響 task 數 + 手動恢復按鈕；按下 → state=closed + 影響 task 重 enqueue
- 資料模型留 `task_type` 欄位（v1 暫不分 task type，未來細粒度按鈕直接擴充 UI）
- 新增 **provider fallback chain**：當 aihub 收到 ContentPolicyViolation / budget_exceeded / insufficient_quota 永久錯時，task **自動嘗試一次 OpenAI direct fallback**（用硬編碼模型映射表）；fallback 成功 → 不觸發 circuit、failure log 標 `recovered via fallback`；fallback 也失敗 → 寫兩列 log，各自走自己 provider 的 circuit 計數。直接動機：5/10 同日 Azure 內容過濾擋掉許多中文 podcast topic 分類，OpenAI direct 沒這個過濾器

## Non-Goals

- 不做按 task type 細粒度 resume 按鈕（v2 改 UI 即可，v1 先做按 provider 一個）
- 不做 task 本身的功能修補（如修 silent drop 根因 — 屬 F1 範疇，已 propose）
- 不做 SMS / Slack / PagerDuty 通知（只用 ZSend Email）
- 不做 metrics dashboard 圖表（屬 R1.3 Langfuse 整合範疇）
- 不做跨 worker / 跨 service 分散式狀態同步（state 集中在 Postgres，Beat 單實例 polling 即可）
- 不引入新外部服務（不裝 Sentry / Datadog；觀測寫進既有 ZSend + DB）
- 不動 F1 的 queue routing / dispatcher fix（依賴 F1 archive 後才開做）

## Capabilities

### New Capabilities

- `task-failure-monitoring`: 記錄 Celery task 失敗事件、滑動窗口告警、錯誤分類為暫時/永久
- `service-circuit-breaker`: 外部 provider 永久錯閾值觸發暫停、task 進場 circuit check、自動 sentinel probe 探測、admin 手動恢復按鈕、影響 task 重 enqueue

### Modified Capabilities

（無 — 新功能集中在兩個新 capability，既有 api-health-tracking 不變動行為）

## Impact

- Affected specs: `task-failure-monitoring`、`service-circuit-breaker`
- Affected code:
  - New:
    - `backend/alembic/versions/<timestamp>_add_task_failure_log_and_circuit_state.py`（新表 migration）
    - `backend/app/models/task_failure_log.py`
    - `backend/app/models/service_circuit_state.py`
    - `backend/app/services/circuit_breaker.py`（state 讀寫 + provider 解析 + check 介面）
    - `backend/app/services/error_classifier.py`（exception → permanent / transient 判定）
    - `backend/app/workers/failure_alert.py`（Beat task：滑動窗口統計 + ZSend 寄信）
    - `backend/app/workers/circuit_probe.py`（Beat task：sentinel probe）
    - `backend/app/api/admin_circuit.py`（admin REST：list state / manual resume）
    - `backend/tests/test_error_classifier.py`
    - `backend/tests/test_circuit_breaker.py`
    - `backend/tests/test_failure_alert.py`
    - `backend/tests/test_circuit_probe.py`
    - `backend/tests/test_admin_circuit_api.py`
    - `src/AdminPage.jsx` 新 ServiceStatusTab 元件區塊
  - Modified:
    - `backend/app/workers/celery_app.py`（beat_schedule 加 failure_alert 跟 circuit_probe）
    - `backend/app/workers/tasks.py`（transcribe_episode 進場加 circuit check + Task.on_failure 寫 failure log）
    - `backend/app/workers/topic_task.py`（同上）
    - `backend/app/workers/summary_task.py`（同上）
    - `backend/app/services/zsend.py`（新增 send_failure_alert / send_recovery_notice helper）
    - `src/AdminPage.jsx` 加新 tab 路由（page='admin-service-status'）
    - `src/Shared.jsx` admin nav 加 「服務狀態」連結
