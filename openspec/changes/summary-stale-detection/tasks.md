## 1. 資料庫欄位與 Model（Requirement: Episodes table stores AI summary state）

- [x] 1.1 在 `backend/app/models/episode.py` 的 `Episode` model 加 `ai_summary_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)` 與 `ai_summary_error: Mapped[str | None] = mapped_column(Text, nullable=True)` 兩個欄位
- [x] 1.2 在 `backend/alembic/versions/` 新增 revision `<rev>_add_ai_summary_started_at_and_error.py`：`op.add_column('episodes', ai_summary_started_at TIMESTAMP WITH TIME ZONE NULL)`、`op.add_column('episodes', ai_summary_error TEXT NULL)`，並在 upgrade 末尾執行 `UPDATE episodes SET ai_summary_started_at = now() WHERE ai_summary_status = 'running'`（避免 migration 跑完馬上被視為 stale）；downgrade 兩個 drop_column（對應「Episodes table stores AI summary state」需求修訂）
- [x] 1.3 在 `backend/app/schemas/episode.py` 與 `backend/app/schemas/queue.py` 對外 schema 加 `ai_summary_error: str | None`（admin queue 回應用）

## 2. Settings

- [x] 2.1 在 `backend/app/core/config.py` 的 `Settings` class 加 `summary_stale_threshold_seconds: int = 600`，命名 env `SUMMARY_STALE_THRESHOLD_SECONDS`，加 docstring 說明用途與單位
- [x] 2.2 在 `backend/tests/test_config.py` 加一個 case 確認預設值是 600 且能由 env 覆寫

## 3. Celery summary task：started_at + on_failure + 冪等（Requirement: Map-reduce summary task with retries）

- [x] 3.1 在 `backend/app/workers/summary_task.py` 把 status 從 pending/failed 改為 running 的 UPDATE 同時 set `ai_summary_started_at = func.now()`；transition to done 時 set `ai_summary_error = None`；transition to failed (after 3 retries) 時 set `ai_summary_error = repr(exc)[:1000]`（對應「Map-reduce summary task with retries」需求修訂）
- [x] 3.2 在 `generate_episode_summary` 的 `@celery_app.task(...)` 裝飾器加 `bind=True`（若還沒有），實作 `on_failure(self, exc, task_id, args, kwargs, einfo)` 方法：開新 DB session，先 SELECT row，若 `ai_summary_status != 'done'` 才 UPDATE 為 `failed`、`ai_summary_generated_at=now()`、`ai_summary_error=repr(exc)[:1000]`；若 SELECT/UPDATE 失敗則 log exception 但不 raise（避免 Celery 反覆重試 on_failure）
- [x] 3.3 確認 task 入口的 idempotent short-circuit（spec 既有的「status==done 或 running 早返」）邏輯保留不動；補一行 debug log 印 `started_at` 方便日後排查

## 4. cron_tick stale summary detection（Requirements: Cron tick recovers stale-running summary rows + Cron tick scans for stale-running summary tasks）

- [x] 4.1 在 `backend/app/workers/cron_tick.py` 新增 `async def _detect_stale_summary_running(session_factory) -> int`，回傳本次 recovered 的 row 數（對應「Cron tick recovers stale-running summary rows」與「Cron tick scans for stale-running summary tasks」需求）
- [x] 4.2 helper 內部：`SELECT id, ai_summary_started_at FROM episodes WHERE ai_summary_status='running' AND ai_summary_started_at IS NOT NULL AND ai_summary_started_at < now() - INTERVAL ':n seconds'`，binding `n = settings.summary_stale_threshold_seconds`；對每一列開 sub-transaction，UPDATE 為 `pending` + 清 started_at + 寫 `ai_summary_error='recovered from stale running after <elapsed>s'`，commit 後 call `generate_episode_summary.delay(episode_id)`；若 delay 拋例外則 rollback 該列的 UPDATE 並 log warning，繼續下一列
- [x] 4.3 處理「`ai_summary_status='running'` 但 `ai_summary_started_at IS NULL`」的防禦性分支：另一條 SELECT 撈出這類列，只 log warning 印出 row id，不做任何 UPDATE
- [x] 4.4 在 `_run_tick` 既有的「stale_marked = await _detect_stale_running(...)」之後加上 `try/except` 包住 `summary_recovered = await _detect_stale_summary_running(Session)`，例外只 log 不 raise
- [x] 4.5 在 tick 結尾的回傳 dict 加 `'stale_summary_recovered': summary_recovered`，方便看 Celery task result

## 5. Admin API 與前端 UI（Requirement: Admin queue response exposes summary error message）

- [x] 5.1 在 `backend/app/api/admin.py`（或實際的 queue endpoint 檔案，可能在 `backend/app/api/admin/queue.py`）的 queue 回應 serialization 加上 `ai_summary_error` 欄位（從 episodes 表 JOIN 出來，若 NULL 就回 null）（對應「Admin queue response exposes summary error message」需求）
- [x] 5.2 在 `src/AdminPage.jsx` 的 `SummaryBadge` 元件：當 `ai_summary_status === 'failed'`，render `<span title={ai_summary_error || '...fallback...'}>` 顯示 error tooltip；fallback 字串繁中「摘要失敗（未記錄錯誤訊息）」、英文 `"Summary task failed (no error message recorded)"`，依 `lang` 切換
- [x] 5.3 若 `ai_summary_error` 長度超過 200 字元，UI tooltip 截斷加 `…`（避免 hover 出現巨大區塊）

## 6. 測試

- [x] 6.1 新增 `backend/tests/test_cron_tick.py`（若不存在），加測試：建立一筆 stale episode → 跑 `_detect_stale_summary_running` → assert row 被 reset、`generate_episode_summary.delay` 被呼叫一次（mock）、回傳 1
- [x] 6.2 同檔加測試：fresh running row（started_at=now-60s）+ threshold=600 → 不被動到，回傳 0
- [x] 6.3 同檔加測試：running row 但 started_at IS NULL → 不被動到，僅 log warning（用 caplog 驗證）
- [x] 6.4 同檔加測試：3 筆 stale，第一筆的 `delay` mock 拋 RuntimeError → 第一筆 rollback 維持 running、後兩筆成功 reset，回傳 2
- [x] 6.5 在 `backend/tests/test_summary_pipeline.py` 或 `backend/tests/test_summary_integration.py` 加測試：task 執行進入 running 時 `ai_summary_started_at` 被寫入；done 後仍保留該值
- [x] 6.6 同上加測試：on_failure 觸發時 row 變 failed、`ai_summary_error` 非空且 ≤1000 字元；若 row 已是 done 則 on_failure 不覆寫
- [x] 6.7 驗證所有既有 summary 相關 pytest 仍綠：`pytest backend/tests/test_summary_pipeline.py backend/tests/test_summary_integration.py backend/tests/test_episode_summary_api.py backend/tests/test_admin_summary_ops.py`

## 7. 部署與驗證

- [x] 7.1 執行 `pytest backend/tests/` 全綠
- [ ] 7.2 commit 並 push 到 main，觀察 Zeabur 4 service（backend / worker / dispatcher / beat）build & deploy 全綠；`backend` 的 entrypoint 會跑 `alembic upgrade head` 自動套用 migration
- [ ] 7.3 prod 驗證 1：透過 e2e-login 後門登入，確認 `GET /admin/queue` 回應每筆都有 `ai_summary_error` 欄位（多數為 null）
- [ ] 7.4 prod 驗證 2：手動製造一個 stale 情境（在 DB 把某筆 `ai_summary_status='done'` 的 row 改回 `running` 且 `ai_summary_started_at = now() - 700s`），等下一個 cron_tick（≤1 min），確認 row 被 reset 為 pending、`ai_summary_error` 寫入 recovered 訊息、Celery task 重跑後變回 done
- [ ] 7.5 prod 驗證 3：把該 row 的 ai_summary 還原到原值（避免污染資料）
- [ ] 7.6 更新 `docs/roadmap.md` 與 `project_pending_changes.md` 記憶（archive 後做）
