## Context

`db-driven-queue-and-real-cron`（archived 2026-04-28）導入 DB-backed `transcription_queue` 與 `cron_tick` Celery Beat 任務（每分鐘掃 schedules + enqueue）。`parallel-transcription-and-force-cancel`（archived 同日）加上 `celery_task_id` 欄位 + force-cancel API。

但今日 prod 觀察到問題：worker 改 `--concurrency=3` redeploy 時，broker 中正在派發的 task 訊息遺失（broker 沒收到 ack 也沒 requeue，或 worker 收到後 silent crash）。受影響 row：`13b470f2`/EP238（卡 4 小時）、`2a4ce7d2`/EP243（卡 76 分鐘）。當下需手動 force-cancel 清。

需要的是「DB row 與 Celery worker 實際狀態的對帳機制」：定期對比 DB 中 `status=running` 的 row 與 Celery 實際在跑的 task，差集 = 卡住的 row。

## Goals / Non-Goals

**Goals**
- 偵測 + 自動標 stale running row 為 failed（30 分鐘 + Celery inspect 雙條件）
- 釋放 Redis throttle slot 讓 dispatcher cap 恢復
- 失敗 / inspect timeout 不影響 cron_tick 主流程

**Non-Goals**
- 不 auto re-enqueue（UI 重試按鈕已存在）
- 不調整閾值為動態 setting
- 不偵測 stuck pending / broker 訊息積壓
- 不為 inspect 失敗 retry（skip 該 tick，下分鐘自然重試）
- 不加新 UI（沿用失敗 row 既有顯示）

## Decisions

### 偵測位置：cron_tick 內加子流程，不開新 Beat 任務

選擇：在 `_run_tick()` 開頭（schedule 處理之前）呼叫 `_detect_stale_running(Session)`。

**為什麼不開新 Beat task**：
- cron_tick 已每分鐘跑、已建好 async DB session pattern + engine 管理
- 新 task 要在 `celery_app.py` 的 `beat_schedule` dict 加條目、加新 task name、新 module — 多 ~30 行 boilerplate
- 兩件事（schedule fire + stale detection）都是「每分鐘對帳 DB」的邏輯，放同一處更易閱讀

**順序**：stale detection 跑在 schedule 處理之前。理由：先對帳釋放 slot，dispatcher 才能在後續分鐘內把新 enqueue 的 row promote。

### Stale 定義：30 分鐘 AND 不在 Celery active∪reserved

**雙條件**：
1. `started_at < now - 30 minutes`
2. AND（`celery_task_id IS NULL` OR `celery_task_id NOT IN celery_app.control.inspect().active() ∪ reserved()`）

**為什麼是 30 分鐘**：典型 Whisper 一集 5–15 分鐘；給 2x buffer 讓長尾正常結束。Celery `task_acks_late=True`（已設）意味著 task 未完成不會 ack，但訊息遺失場景 broker 也不會 requeue（因為 worker 已 disappear）。

**為什麼還要查 inspect**：單看時間會誤殺正在跑的長尾 task。`inspect()` 直接問 worker「你現在在跑哪些 task」，是判斷「真的還在跑」的權威來源。

**為什麼 `celery_task_id IS NULL` 視為 stale**：worker 在 `_write_celery_task_id`（任務開頭第一個動作）之前 crash 的場景。30 分鐘還沒寫 task_id 就是 stale，不需查 inspect。

### Inspect 設計：5 秒 timeout + 失敗 skip

```
i = celery_app.control.inspect(timeout=5)
active = i.active() or {}
reserved = i.reserved() or {}
running_ids = set()
for worker_tasks in active.values():
    running_ids.update(t['id'] for t in worker_tasks)
for worker_tasks in reserved.values():
    running_ids.update(t['id'] for t in worker_tasks)
```

**為什麼 timeout=5**：default 1 秒對 broker 跨網段 / 多 worker 容易假陰性；5 秒 worst case，cron_tick 整體 budget < 60 秒（一分鐘一次）有充足空間。

**inspect 拋例外處理**：`try/except Exception` 包住整個 detection 子流程；失敗 log 警告後 return（不影響後續 schedule 處理）。下分鐘自然重試。

**`active().values()` 拿不到 worker（broker 暫時掛掉等）**：returns None or empty dict → `running_ids` 集合為空 → 所有過期 row 都會被當成 stale。Mitigation：**inspect 回傳空集合時也視為 inspect 失敗，跳過 detection**。判斷方式：`if not active and not reserved: skip`。

### 動作：標 failed、不 re-enqueue

```
row.status = QueueStatus.failed
row.finished_at = datetime.now(timezone.utc)
row.error_message = 'Stale task — worker message lost'
if row.celery_task_id:
    release_global_slot(row.celery_task_id)
```

**為什麼 failed 不是 cancelled**：
- `cancelled` 語意是「使用者主動取消」（普通 cancel + force-cancel 都是）
- `failed` 語意是「系統判定無法完成」，更貼合 stale 場景
- failed row 在 UI 觸發「重試」按鈕；cancelled 不會（cancelled 沒有重試按鈕）— 這對使用者體驗更好

**為什麼不 auto re-enqueue**：訊息遺失原因不明（broker bug? code bug? 配額耗盡 silent fail?），auto re-enqueue 可能無限循環。讓使用者看到 + 按重試決定。

### Slot 釋放：跟 force-cancel 同邏輯

`release_global_slot()` 原子性 `r.decr(GLOBAL_ACTIVE_KEY)` + `r.delete(GLOBAL_SLOT_KEY)`。即使 Redis slot TTL（7200 秒 = 2 小時）會自動過期，主動釋放讓 dispatcher cap 立刻恢復。

celery_task_id=null 時跳過 release（因為當初也沒 acquire；`acquire_global_slot` 寫的 key 是 task_id，task_id=null 表示連 acquire 都沒做）。

## Risks / Trade-offs

- **inspect 假陰性誤殺**：broker 慢或 worker 不回 → row_id 不在 active list → 誤判 stale → 標 failed 中斷正在跑的轉錄。Mitigation：
  - 雙條件要求 `started_at` 也 > 30 分鐘，正常 task 來不及到 30 分鐘就完成
  - inspect 拿不到任何 worker 時整體 skip（避免「broker 掛了 → 全部誤判 stale」災難）
  - 5 秒 timeout 給足夠回應時間
- **inspect 廣播成本**：每分鐘一次 broadcast，每次 5 秒（最多）— 對 broker 負載可忽略（podcast 流量小）
- **30 分鐘閾值對「真的需要更久」的 task**：寫死常數無法處理。當前 Whisper 走 OpenAI API，最長集 ~15 分鐘可預期。若未來有更長集，需改 code（已記入 Non-Goals）
- **race condition：detection 跑時 worker 剛好完成**：worker `_mark_queue_finished` 與 detection `_mark_stale` 同時寫同一 row。SQLAlchemy session 隔離 + last-write-wins，最壞情況一個 row 被連續寫兩次同個 finished_at，無正確性問題

## Migration Plan

1. 部署 backend（含 cron_tick 修改 + 新測試檔）
2. 等下一個 cron tick（最多等 60 秒）
3. prod 驗證：
   - 預埋一筆 stale row（手動 UPDATE row 把 started_at 改 1 小時前 + 隨機 celery_task_id）
   - 等 cron_tick 跑一輪
   - 確認 row 變 failed + error_message 正確 + slot 釋放
4. （可選）確認真實 long-running task 不被誤殺：壓一集 podcast 跑 25 分鐘觀察其間 detection 不動它

**Rollback**：移除 cron_tick 內 `_detect_stale_running` 呼叫即可，無 schema 改動。

## Open Questions

無。所有設計點已對齊（discuss 階段已 confirm 5 個決定 + 風險討論）。
