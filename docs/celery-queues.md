# Celery Queue 模型（celery-routing-and-dispatcher-fix）

PodcastRAG 的 Celery worker 採「**單 worker service / 多 queue 訂閱 / message priority**」模型，自 `celery-routing-and-dispatcher-fix` 起改為 4 條 queue：

| Queue        | 用途                                                                 | 預設 priority |
|--------------|----------------------------------------------------------------------|--------------|
| `transcribe` | `transcribe_episode`（Whisper 轉錄）                                  | 9（高）      |
| `topic`      | `classify_episode_topics`（topic_label 批次分類）                     | 2（低）      |
| `summary`    | `generate_episode_summary`（每集 AI 摘要）                            | 2（低）      |
| `control`    | cron_tick / quota_digest / eval_reminder / db_backup / tokenizer_reload / usage_collector / usage_alert + 預設 fallback | 5（中）   |

## 為什麼這樣拆

- **transcribe priority=9**：confirm slot 一空，broker 一定先送 transcribe，不會被 backfill 擠住（EP20 9 小時阻塞案例）。
- **topic / summary priority=2**：backfill 一次 enqueue 數百個 task 也不影響 transcribe / 雜事。
- **control queue 分離**：寄信 / 備份 / cron 不會被 backfill 拖延。
- **task_default_queue=control**：新 task 若忘記設 routes 不會被靜默丟棄。

## Worker 啟動

`entrypoint.sh` 偵測 `START_COMMAND` 是 `celery ... worker` 時，若沒帶 `--queues` 旗標就預設補上：

```
celery -A app.workers.celery_app worker --loglevel=info --concurrency=6 \
    --queues=transcribe,topic,summary,control
```

Zeabur worker service `START_COMMAND` env 不需要改，entrypoint 會自動補；想覆寫就在 env 寫完整指令含 `--queues=...`。

## Dispatcher 行為

`backend/app/workers/dispatcher.py` 只負責 `send_task`，**不再** update `transcription_queue.status` / `started_at` / `celery_task_id`。row state 由 worker task entry 的 `_claim_queue_row` 在 `SELECT FOR UPDATE` 區段內 atomic transition：

| 進場時 row 狀態                            | 行為                          |
|--------------------------------------------|-------------------------------|
| `status=pending`                           | claim → running + 寫 task_id  |
| `status=running` AND started_at <5min      | 視為 duplicate，ack & skip    |
| `status=running` AND started_at >5min/NULL | reclaim → 更新 task_id        |
| `status` ∈ cancelled/completed/failed/ignored | ack & skip                |

## Redis broker priority

`celery_app.py` 設定 `broker_transport_options={"priority_steps": [0, 3, 6, 9]}`、`task_queue_max_priority=10`、`task_default_priority=5`、`worker_prefetch_multiplier=1`。Redis broker 把每個 priority bucket 變獨立 sub-list；slot 釋放時優先 pop 高 priority bucket。
