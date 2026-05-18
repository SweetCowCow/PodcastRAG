# Celery Queue 模型

更新於 2026-05-18（change: `celery-routing-and-dispatcher-fix`）。

## 為什麼拆 queue

之前所有 task 共用單一 default queue `celery`，FIFO + concurrency=6。
R3.2 backfill 一次塞 300+ 個 topic task 就把 transcribe / 寄信 / 備份等
高優先任務全擠到隊尾（EP20 2026-05-10 卡 9+ 小時的根因）。

## 四條 queue

| Queue | 用途 | 預設 priority |
|-------|------|--------------|
| `transcribe` | `transcribe_episode` — Whisper 轉錄（最貴最不能等） | 9（高）|
| `topic` | `classify_episode_topics` — topic backfill | 2（低）|
| `summary` | `generate_episode_summary` — AI 重點摘要 | 2（低）|
| `control` | cron_tick / quota_digest / db_backup / eval_reminder / tokenizer_reload / appeal_digest / usage_collector / usage_alert / 任何未顯式 route 的 task | 5（預設）|

`task_default_queue = "control"` —— 新 task 沒設 route 自動走 control，
不會神祕地不執行。

## Worker 配置

單一 worker service，`--queues=transcribe,topic,summary,control --concurrency=6`。
Celery 配置 `worker_prefetch_multiplier=1` 確保 worker 不囤積，slot
釋放時 broker 馬上重排序、優先送高 priority 訊息給空 slot。

不拆雙 worker service（discuss 結論：priority + prefetch=1 已能解決
EP20，雙 service 月費 +$3-5 + RAM 浪費 + 命名混亂）。

## Priority 與 priority_steps

- `task_queue_max_priority=10`
- `task_default_priority=5`
- `broker_transport_options={"priority_steps": [0, 3, 6, 9]}`

只支援 Redis broker（priority_steps 是 Redis 專屬實作；
RabbitMQ 行為不同，沒驗）。

## Zeabur 部署

worker service `START_COMMAND` 必須顯式帶 `--queues`：

```
celery -A app.workers.celery_app worker --loglevel=info --concurrency=6 --queues=transcribe,topic,summary,control
```

`entrypoint.sh` 有安全網：若 `START_COMMAND` 是 celery worker 但漏帶
`--queues`，會自動補預設四條（避免 deploy 設定漏改造成 silent breakage）。

## 部署後驗證

```
celery -A app.workers.celery_app inspect active_queues
```

應該看到 worker 訂閱了 transcribe / topic / summary / control 四條。
