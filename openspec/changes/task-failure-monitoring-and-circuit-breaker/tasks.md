## 1. DB schema 與基礎設置

- [x] 1.1 寫 alembic migration 新建兩表：`task_failure_log`（id / task_name / task_args_json / failure_type / error_class / error_message / provider_id / retry_count / failed_at / alerted_at / recovered_at + 索引）+ `service_circuit_state`（provider_id PK / task_type / state / opened_at / paused_task_count / last_probe_at / last_probe_result / manual_resumed_by / manual_resumed_at），以及 PG enum types（落實 Decision: 失敗事件寫 Postgres `task_failure_log` 表，不沿用 Redis ring buffer + Decision: Circuit breaker 狀態存 PG `service_circuit_state` 表，不用 Redis + Requirement: Persisted task failure log + Requirement: Service circuit state table）
- [x] 1.2 在 backend startup hook 加 seed 3 個 provider rows（openai / aihub / zsend）邏輯：若 row 不存在則建立 default state='closed'；若已存在則保留
- [x] 1.3 加 daily cleanup beat task 定期刪 `task_failure_log` 中 `failed_at < NOW() - INTERVAL '30 days'` 的舊 row（每天凌晨 4 點 UTC 跑）

## 2. Error classifier

- [x] 2.1 寫 `backend/app/services/error_classifier.py`：暴露 `classify(exc) -> 'permanent' | 'transient' | 'unknown'`，用「白名單永久錯」清單比對 HTTP status / body text / Celery exception class（落實 Decision: 錯誤分類用「白名單永久錯」而非「白名單暫時錯」 + Requirement: Error classifier categorises exceptions as permanent or transient）
- [x] 2.2 寫 `backend/tests/test_error_classifier.py`：覆蓋 spec example table 全部 10 個 case（401/402/415/400 with body/400 plain/429/503/timeout/NotRegistered/KeyError）

## 3. Failure log 寫入 + permanent short-circuit

- [x] 3.1 寫 `backend/app/services/failure_log.py` 提供 `write_failure_log(task_name, args, exc, provider_id, retry_count) -> uuid` helper，內部呼叫 error_classifier 決定 failure_type
- [x] 3.2 改 5 個 worker（tasks / topic_task / summary_task / quota_digest / eval_reminder）的 `Task.on_failure` 處理器（或對應的 base class）：呼叫 `write_failure_log(...)` 寫一列
- [x] 3.3 改同 5 個 worker 的 try/except 結構：先 classify exception，permanent 直接寫 log + raise（不 retry）；transient/unknown 走既有 Celery autoretry 路徑（落實 Requirement: Permanent errors short-circuit Celery retry）

## 4. Circuit breaker open 邏輯

- [x] 4.1 寫 `backend/app/services/circuit_breaker.py` 暴露 `is_open(provider_id, task_type=None) -> bool`、`open(provider_id, reason)`、`close(provider_id, by, kind)`、`increment_paused(provider_id)` 四個函式；都用 PG row-level lock + atomic UPDATE 實作
- [x] 4.2 在 `failure_log.write_failure_log` 內部，當 failure_type='permanent' AND provider_id 非 NULL 時，評估「過去 5 min 該 provider 的 permanent 錯數量 ≥ 3」→ 呼叫 `circuit_breaker.open(provider_id)` + 寄 ZSend 開信（落實 Requirement: Circuit breaker opens on permanent error threshold，含 race scenario：用 `UPDATE ... WHERE state='closed' RETURNING ...` atomic）
- [x] 4.3 寫 `backend/tests/test_circuit_breaker.py` 覆蓋：3rd error opens / 2nd error doesnt / concurrent race ends with single transition

## 5. Task entry circuit check（自我 retry）

- [x] 5.1 在 5 個 worker（transcribe_episode / classify_episode_topics / generate_episode_summary / send_quota_digest / send_eval_reminder）task entry 加 circuit check：呼叫 `circuit_breaker.is_open(provider_id)`，若 True → `circuit_breaker.increment_paused(provider_id)` + `raise self.retry(countdown=300, max_retries=None)`（落實 Decision: Task 進場 circuit check 用「自我 retry 5 min 後」而非「拒收 task」 + Requirement: Tasks check circuit state on entry and self-retry when open）

## 6. Beat tasks（failure alert + sentinel probe + ZSend helper）

- [x] 6.1 寫 `backend/app/workers/failure_alert.py`：每 5 min 跑，scan task_failure_log 找 30 min 滑動窗口失敗 ≥ 3 次 AND alerted_at IS NULL 的 task_name；呼叫 ZSend 寄信後把該批 row update alerted_at=NOW()（落實 Decision: ZSend 失敗告警去重，不要 30 min 內每分鐘都寄 + Requirement: Sliding-window failure rate alert）
- [x] 6.2 寫 `backend/app/workers/circuit_probe.py`：每 30 min 跑，scan service_circuit_state 中 state='open' 的 row；對每個 open provider 呼叫對應 probe func（OpenAI chat ping / AI Hub chat ping / ZSend usage GET）；成功 → close circuit + 寄恢復信，失敗 → 維持 open（落實 Decision: Sentinel probe 用「該 provider 現有 task 模板的 dummy 變體」 + Requirement: Sentinel probe attempts auto-recovery every 30 minutes）
- [x] 6.3 在 `celery_app.py` beat_schedule 加 `failure-alert`（cron `*/5 * * * *`）跟 `circuit-probe`（cron `*/30 * * * *`）兩個 entry
- [x] 6.4 在 `backend/app/services/zsend.py` 新增 `send_failure_alert(task_name, count, errors, taipei_ts)` 跟 `send_recovery_notice(provider_id, opened_at, closed_at, paused_count)` 兩個 helper，內文純文字繁中
- [x] 6.5 寫 `backend/tests/test_failure_alert.py`：覆蓋 5 個 scenario（3 errors triggers email / 2 errors no trigger / already-alerted not re-alerted / ZSend send failure leaves un-alerted / ZSend not configured logs and skips）
- [x] 6.6 寫 `backend/tests/test_circuit_probe.py`：覆蓋 3 個 scenario（successful probe closes / failed probe stays open / closed not probed）

## 7. Admin REST API

- [x] 7.1 寫 `backend/app/api/admin_circuit.py`：`GET /admin/service-status` 列 3 row JSON、`POST /admin/service-status/{provider_id}/resume` 用 atomic UPDATE 把 open → closed + 記 manual_resumed_by/at + 標 task_failure_log.recovered_at（落實 Decision: Admin 手動恢復「按 provider 一個 button」+ 資料模型留 task_type 欄位 + Requirement: Admin endpoints expose circuit state and manual resume）
- [x] 7.2 把 admin_circuit router 註冊進 main.py 並掛 admin 角色 + CSRF middleware（沿用既有 require_admin pattern）
- [x] 7.3 寫 `backend/tests/test_admin_circuit_api.py`：覆蓋 4 個 scenario（GET 回 3 rows / POST resume open→closed / POST resume already-closed 回 409 / non-admin 回 403）

## 8. Admin UI

- [x] 8.1 在 `src/AdminPage.jsx` 加新 `ServiceStatusTab` 元件：fetch `/admin/service-status`、render table（供應商 / 狀態 badge / 暫停起時 / 影響 task 數 / 最後探測 / 操作）、套用 TOKEN 配色、時間欄用 `Intl.DateTimeFormat('zh-TW', {timeZone:'Asia/Taipei'})`、open badge 紅 closed badge 綠（落實 Requirement: Admin UI shows service status with manual resume button）
- [x] 8.2 在 `src/Shared.jsx` admin nav 加「服務狀態」連結，對應 page route `admin-service-status`，加進 AdminPage routing
- [x] 8.3 ServiceStatusTab 加 [⏵ 手動恢復] button（state='open' 啟用 / 'closed' 灰）+ 確認 modal「確定要手動恢復 <provider_id> 服務嗎？影響 <count> 個任務會重新加入 queue。」 + POST resume + success/409 toast

## 9. Provider fallback chain（aihub fail → OpenAI direct）

- [x] 9.1 在 `backend/app/services/circuit_breaker.py` 加 `try_fallback(provider_id, payload, model) -> tuple[result, fallback_used: bool]` 函式，內部用硬編碼 `AIHUB_TO_OPENAI_MODEL_MAP` dict 對應映射；失敗時回 `(None, False)`，成功回 `(response, True)`（落實 Requirement: Permanent provider error triggers fallback provider attempt + Decision: aihub 永久錯啟用 OpenAI direct fallback once）
- [x] 9.2 在 5 個 worker task 的 permanent error 處理路徑（接續 task 3.3），對 `provider_id='aihub'` 且 exception 屬 `ContentPolicyViolationError | budget_exceeded | insufficient_quota` 三種：呼叫 `try_fallback(...)`；成功 → 寫 `task_failure_log` 為 transient + recovered_at + 不觸發 circuit；失敗 → 寫兩列 failure log（aihub + openai），各自走 circuit 計數
- [x] 9.3 寫 `backend/tests/test_circuit_breaker_fallback.py`：覆蓋 5 個 scenario（ContentPolicy → fallback success / Budget → fallback success / both fail records two rows / openai direct no fallback / unknown model skips fallback）+ mapping table 表

## 10. 部署 + smoke

- [ ] 10.1 commit + push main → CI 全綠 → Zeabur 4 service rebuild redeploy
- [ ] 10.2 prod smoke 1：在 admin 把 aihub ai_steps key 暫時改錯 → 觸發任一 transcribe / topic task → 確認 5 min 內收 ZSend 失敗告警信 + circuit 開 + admin UI 紅 badge + paused_task_count 增長 + 手動 resume 後恢復 + recovery 信寄出
- [ ] 10.3 prod smoke 2：把 aihub 模型故意切到會觸發 ContentPolicy 的中文敏感字 prompt → 觀察 task fallback 走 OpenAI direct 完成 + log 標 `recovered via fallback` + circuit 仍 closed
- [ ] 10.4 release log 補對應 entry（user 視角白話文：「外部 API 出問題會自動暫停 + 寄信通知 + Zeabur 卡 Azure 過濾自動切回 OpenAI」）+ 同步路線圖把 F2 從 💬 改 📦
