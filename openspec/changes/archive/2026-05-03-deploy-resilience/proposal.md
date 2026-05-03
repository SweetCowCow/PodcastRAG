## Summary

讓部署不再中斷正在跑的轉錄任務、不再產生 ghost running rows，並修補 force-cancel 的 throttle slot 釋放漏洞。

## Motivation

2026-05-02 的 `authentication-system` 部署暴露三個問題：

1. **跨服務 env 配置漏設**：`GOOGLE_*` / `SESSION_SECRET` 改成 pydantic-settings required 之後，dispatcher 與 beat 兩個 Celery 服務沒設這些 env，啟動就 ValidationError → 死掉 → pending row 沒人 dispatch（5 小時無進度）+ stale-running-detection cron 也死了（沒人清 ghost）。
2. **Worker 被 SIGKILL 留 ghost**：deploy 時舊 worker 容器被砍，但 DB 仍標 `running` + Celery 已遺失該 task → row 卡 4 小時、`stale-running-detection` 預設 30min 後才會清（這是事故發生時的「最佳結果」，且仍要等 30min 而非立即恢復）。
3. **Force-cancel NULL task_id 漏洞**：`backend/app/api/queue.py:102` `if task_id:` 守住 → ghost row 若沒 celery_task_id 就 skip `release_global_slot`，throttle counter 卡死，pending 拿不到 slot。

事故過後 LLM 額度浪費 + 5 小時轉錄停擺，無法事後挽回。需要根本性的部署韌性。

## Proposed Solution

### A. Service-aware required env（解決 #1）

把 `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` / `SESSION_SECRET` 改回 `Optional[str] = None`。在 web 服務啟動時（`backend/app/main.py` 的 lifespan startup）做 explicit runtime 檢查：若四個 env 任一為空 → log 錯誤 + 拋 RuntimeError 阻止 backend 啟動。Worker / dispatcher / beat 啟動因為不 import `app.main`，這四個 env 缺失時不會崩潰。`/auth/*` 與 `/me` router 在每個 endpoint handler 入口再次驗 env 已設（防呆）。

### B. Worker graceful shutdown（解決 #2 主對策）

在 Celery worker 註冊 `worker_shutting_down` signal handler。觸發時：
- 對 worker 此刻擁有的所有 active task 對應的 `transcription_queue` row（用 row id 從 task args 取）做 `UPDATE ... SET status='pending', started_at=NULL, celery_task_id=NULL WHERE id IN (...)`。
- 釋放對應 throttle slot（`release_global_slot(row_id_str)` — 改 ownership key 為 row_id 以避免 #3 的 NULL 漏洞）。
- 給 30 秒 grace window（透過 Celery `worker_proc_alive_timeout` 與 SIGTERM grace），讓 in-flight Whisper API call 自然結束或被中斷。

效果：deploy → SIGTERM → graceful 把 row 推回 pending → 新 worker 起來 → dispatcher 自動接著跑。**「沒有 ghost row」+ 「沒有卡 throttle」**。

### C. Worker startup self-recovery（解決 #2 後備）

graceful shutdown 不一定每次成功（OOM-kill / kubelet 強砍 / 程式崩 panic）。Worker 啟動時主動掃 DB：找 `status='running'` 的 row，若 (`celery_task_id IS NULL`) 或 (對應 task 不在 `celery_app.control.inspect().active()` 集合內) → 推回 pending（同 B 的 row 重置邏輯）。

### D. Force-cancel slot 釋放（解決 #3）

`backend/app/api/queue.py:100-119` 重構：throttle slot ownership 從 task_id 改用 queue row id 當 key。force-cancel 不論 `celery_task_id` 是否為 None，都呼叫 `release_global_slot(str(queue_id))`。`acquire_global_slot` / `release_global_slot` 簽名同步改用 row id。

### E. Pytest 覆蓋

- 跑 worker shutdown signal handler 的單元測試（mock celery active inspect、模擬 1 row running → 觸發 handler → 驗 DB row 變 pending + slot release）
- startup self-recovery 的單元測試（DB 種 1 row running celery_task_id=None + 1 row running with active task → 啟動後第一筆變 pending、第二筆維持 running）
- force-cancel + NULL task_id 整合測試：用既有 `auth_admin` fixture，建 1 row running celery_task_id=None，acquire slot，force-cancel，驗 slot counter 歸零
- web service env 缺失測試：unset GOOGLE_CLIENT_ID 後 import `app.main` 應拋 RuntimeError；worker / dispatcher / beat import 鏈不應拋

## Non-Goals

- **In-flight Whisper API call resume / 續轉**：被中斷的 Whisper 呼叫已經產生的 partial token 不挽救，重新跑整集，LLM 成本浪費。複雜度過高，YAGNI
- **Dispatcher / Beat 健康狀態 UI 指示器**：屬觀察性需求，留下個 change（暫名 `service-health-indicators`）
- **管理員手動「暫停 queue」開關**：B + C 已能 cover deploy 場景，手動暫停沒必要
- **跨多 worker concurrency 的精細語義**：本專案 worker 預期是單一 replica（`--concurrency=3` 在同一 process 內），多 worker pod 的 graceful 互動暫不處理
- **Beat / dispatcher 自身的 graceful shutdown**：他們是 stateless poll loop，被砍重啟即可，不會留 DB 狀態

## Alternatives Considered

- **Optional env + 路徑入口處檢查**（不在 main lifespan 集中檢）：較鬆散，可能漏掉某個 entrypoint；集中在 main lifespan 是 single source of truth。**採用集中式**
- **graceful shutdown 直接把 running 標 cancelled**：使用者體驗差（部署後得手動重新加入 queue）。**採用「推回 pending」自動復跑**
- **完全砍 stale-running-detection、只靠 graceful + startup recovery**：壞掉的 case（如 worker process 死但 pod 還活）就無解。**保留 stale-running-detection 當第三層防線**
- **用 Celery `worker_ready` signal 而非 startup function**：worker_ready 在 worker 接受任務前觸發，但 hook 跟 Celery init 順序有微妙互動；用 `celery_app` 啟動完後第一個 task 之前的明確 startup function 較好掌控

## Impact

- Affected specs:
  - Modified: `openspec/specs/backend-core/spec.md`、`openspec/specs/task-queue/spec.md`、`openspec/specs/transcription-queue/spec.md`
- Affected code:
  - New:
    - backend/app/workers/lifecycle.py（worker shutdown signal + startup recovery）
    - backend/tests/test_worker_lifecycle.py
    - backend/tests/test_force_cancel_throttle.py
    - backend/tests/test_web_service_env_validation.py
  - Modified:
    - backend/app/core/config.py（GOOGLE_* / SESSION_SECRET 改 Optional）
    - backend/app/main.py（lifespan startup 加 web env 必填檢查）
    - backend/app/workers/celery_app.py（import lifecycle、register signals）
    - backend/app/workers/throttle.py（slot ownership 改 row_id；release 不再 short-circuit on falsy key）
    - backend/app/api/queue.py（force-cancel 一律 release slot；ownership key 跟 throttle 同步）
    - backend/app/workers/tasks.py（acquire/release call 點改 row_id）
    - backend/tests/conftest.py（如需，新增 worker shutdown signal helper）
  - Removed: 無
- Deploy step:
  - 完成後重新部署，驗證下次 push 時 dispatcher / beat / worker 都不會炸 + running row 自動推回 pending
