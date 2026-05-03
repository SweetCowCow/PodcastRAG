## 1. Service-aware required env

- [x] 1.1 修改 `backend/app/core/config.py`：把 `google_client_id` / `google_client_secret` / `google_redirect_uri` / `session_secret` 從 `str` 改回 `Optional[str] = None`（對應「Configuration management via environment variables」需求修訂與「Authentication env optional for non-web entrypoints」scenario）
- [x] 1.2 修改 `backend/app/main.py` lifespan startup：在 `seed_llm_config_from_env()` 之前加 `_validate_web_env()` 函式，檢查四個 OAuth env 任一為空即拋 `RuntimeError(f"Web service requires {var_name}")`（對應「Web service requires Google OAuth and session env at startup」需求）
- [x] 1.3 在 `_validate_web_env()` 內針對四個變數逐一檢查並回報具體哪個缺失，避免使用者在 log 看到模糊錯誤
- [x] 1.4 確認 worker (`celery_app`)、dispatcher (`app.workers.dispatcher`)、beat 三個 entrypoint 在 OAuth env 全空時可正常 import + 啟動（手動跑或撰寫 unit test 都可）

## 2. Throttle slot ownership 改用 row id

- [x] 2.1 修改 `backend/app/workers/throttle.py`：`acquire_global_slot(slot_key: str)` / `release_global_slot(slot_key: str)` 簽名與註解改成「呼叫方應傳 row id」；不修改 Redis key 計算邏輯（仍是 GLOBAL_SLOT_KEY.format(slot_key)）（對應「Throttle slot ownership keyed by queue row id」需求）
- [x] 2.2 修改 `backend/app/workers/tasks.py` `transcribe_episode`：所有 `acquire_global_slot` / `release_global_slot` 呼叫改傳 `str(queue_row.id)` 而非 celery task id
- [x] 2.3 修改 `backend/app/api/queue.py` line 100-119 force-cancel 路徑（屬「Cancel pending row」需求修訂）：把 `if task_id:` 守住的整段重寫，無條件呼叫 `release_global_slot(str(queue_id))`；revoke Celery task 仍保留 `if task_id:` 守住（沒 task id 不能 revoke）（對應「Force-cancel a running row with null celery_task_id still releases slot」scenario）

## 3. Worker lifecycle module

- [x] 3.1 建立 `backend/app/workers/lifecycle.py`：開頭 import celery signals (`worker_ready`, `worker_shutting_down`)、定義 module-level `logger`
- [x] 3.2 在 `lifecycle.py` 實作 `_revert_orphan_rows(active_task_ids: set[str], inspect_succeeded: bool)`：純函式接受目前 active+reserved task id 集合，掃 DB `status=running` rows，對 orphan rows（celery_task_id=NULL 或 不在集合）做 UPDATE pending + release_global_slot；inspect 失敗時 conservative 模式（只清 NULL task id rows）（對應「Inspect failure leaves non-null task id rows unchanged」scenario）
- [x] 3.3 在 `lifecycle.py` 實作 `_inspect_active_task_ids() -> tuple[set[str], bool]`：呼叫 `celery_app.control.inspect(timeout=5).active()` + `reserved()`，合併所有 worker 的 task id 並回傳 (set, succeeded_flag)；timeout / 例外 → 回 (set(), False)
- [x] 3.4 在 `lifecycle.py` 註冊 `@worker_ready.connect` handler `_on_worker_ready(...)` 呼叫 inspect → revert orphan rows（對應「Worker reverts orphaned running rows to pending on startup」需求）
- [x] 3.5 在 `lifecycle.py` 註冊 `@worker_shutting_down.connect` handler `_on_worker_shutdown(sig, how, exitcode, **kwargs)`：取 worker 自身 active task 對應的 row ids → UPDATE pending + release slot（對應「Worker reverts running rows to pending on graceful shutdown」需求）
- [x] 3.6 shutdown handler 包 try/except 外層，例外時 logger.exception + 不再 raise（對應「Graceful shutdown handler exception does not crash worker exit」scenario）
- [x] 3.7 修改 `backend/app/workers/celery_app.py`（屬「Celery application setup」需求修訂）：在 `include` 加 `app.workers.lifecycle`，確保 worker 啟動會 register signals（對應「Lifecycle signals registered」scenario）

## 4. 後端測試

- [x] 4.1 撰寫 `backend/tests/test_web_service_env_validation.py`：在 monkeypatch 下 unset GOOGLE_CLIENT_ID，驗 import `app.main` 時 lifespan startup 拋 RuntimeError；同時驗 import `app.workers.celery_app` 不拋（對應「Web service requires Google OAuth and session env at startup」需求）
- [x] 4.2 撰寫 `backend/tests/test_force_cancel_throttle.py`：用 `auth_admin` fixture，建 1 個 show + episode + queue row (status=running, celery_task_id=None)；先 `acquire_global_slot(str(row.id))` 讓 counter 升 1；POST `/admin/queue/{id}/cancel?force=true`；驗 row 變 cancelled + counter 歸零（對應「Force-cancel a running row with null celery_task_id still releases slot」scenario）
- [x] 4.3 撰寫 `backend/tests/test_worker_lifecycle.py` 中 `test_revert_orphan_rows_null_task_id`：用 `db_session` fixture 建 row (status=running, celery_task_id=NULL) → 呼叫 `_revert_orphan_rows(set(), True)` → 驗 row 變 pending（對應「Orphan with NULL task id is reverted on startup」scenario）
- [x] 4.4 在 `test_worker_lifecycle.py` 增加 `test_revert_orphan_rows_task_not_in_active`：建 row (celery_task_id='ghost') → 呼叫 `_revert_orphan_rows({'live-task'}, True)` → 驗 row 變 pending（對應「Orphan with task id not in active list is reverted on startup」scenario）
- [x] 4.5 在 `test_worker_lifecycle.py` 增加 `test_revert_preserves_active_task`：建 row (celery_task_id='live-task') → `_revert_orphan_rows({'live-task'}, True)` → 驗 row 維持 running（對應「Running row with active task is preserved on startup」scenario）
- [x] 4.6 在 `test_worker_lifecycle.py` 增加 `test_inspect_failure_conservative`：建兩 rows，一筆 celery_task_id=NULL、一筆 celery_task_id='unknown'；呼叫 `_revert_orphan_rows(set(), False)` → 驗 NULL 那筆變 pending、unknown 那筆維持 running（對應「Inspect failure leaves non-null task id rows unchanged」scenario）

## 5. 部署 + 驗證

- [x] 5.1 commit + push 觸發 Zeabur build（backend / worker / dispatcher / beat 全部會重新 build）
- [x] 5.2 觀察 build：dispatcher + beat + worker 都應正常啟動（不再因 OAuth env 缺失炸掉，因 env 已設好但 code 也允許缺）
- [x] 5.3 prod 手動觀察：在後台觸發一筆轉錄、確認進入 running、人為從 Zeabur dashboard restart worker 服務、再確認該 row 自動回 pending 並由新 worker dispatch 接著跑（驗證 graceful shutdown + startup recovery）
- [x] 5.4 prod 手動測 force-cancel + null task_id 路徑：建一筆 running row（用 SQL 直插 status=running celery_task_id=NULL）、acquire slot、後台按強制取消、驗 throttle counter 歸零（用 zeabur-service-exec 看 redis）
