from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.core.config import settings

if not settings.celery_broker_url:
    raise RuntimeError("CELERY_BROKER_URL 未設定")

celery_app = Celery(
    "podcastrag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks",
        "app.workers.cron_tick",
        "app.workers.lifecycle",
        "app.workers.summary_task",
        "app.workers.topic_task",
        "app.workers.quota_digest",
        "app.workers.appeal_digest",
        "app.workers.eval_reminder",
        "app.workers.db_backup",
        "app.workers.tokenizer_reload",
        "app.workers.usage_collector",
        "app.workers.usage_alert",
    ],
)

# celery-routing-and-dispatcher-fix: 拆 4 條 queue + message priority
#
# - transcribe: 高優先（priority=9），保 EP 轉錄不被 backfill 擠
# - topic / summary: 低優先（priority=2），給 backfill 跑
# - control: cron_tick / quota_digest / db_backup / eval_reminder /
#            tokenizer_reload / appeal_digest / usage_* 等雜事，預設 priority=5
#
# task_default_queue=control 保證未來新 task 沒設 route 也不會被遺漏
# （至少 worker 會接到，不會 silently 卡在沒人聽的 queue 上）。
#
# Redis broker priority 走 priority_steps sub-queue 模型，4 級 [0,3,6,9]
# 對應 low/default/medium/high；max=10 + default=5。
# Non-Goals: 不支援 RabbitMQ broker（priority_steps 只對 Redis 驗過）。
_TASK_ROUTES = {
    "app.workers.tasks.transcribe_episode": {"queue": "transcribe"},
    "app.workers.topic_task.classify_episode_topics": {"queue": "topic"},
    "app.workers.summary_task.generate_episode_summary": {"queue": "summary"},
    "app.workers.cron_tick.cron_tick": {"queue": "control"},
    "app.workers.quota_digest.send_quota_digest": {"queue": "control"},
    "app.workers.appeal_digest.send_appeal_digest": {"queue": "control"},
    "app.workers.eval_reminder.send_eval_reminder": {"queue": "control"},
    "app.workers.db_backup.run_db_backup": {"queue": "control"},
    "app.workers.tokenizer_reload.broadcast_reload": {"queue": "control"},
    "app.workers.usage_collector.collect_provider_usage": {"queue": "control"},
    "app.workers.usage_alert.evaluate_usage_thresholds": {"queue": "control"},
}

celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_routes=_TASK_ROUTES,
    task_default_queue="control",
    task_queues=(
        Queue("transcribe", routing_key="transcribe"),
        Queue("topic", routing_key="topic"),
        Queue("summary", routing_key="summary"),
        Queue("control", routing_key="control"),
    ),
    task_queue_max_priority=10,
    task_default_priority=5,
    broker_transport_options={"priority_steps": [0, 3, 6, 9]},
    beat_schedule={
        "cron-tick": {
            "task": "app.workers.cron_tick.cron_tick",
            "schedule": crontab(minute="*"),
        },
        "quota-digest": {
            "task": "app.workers.quota_digest.send_quota_digest",
            "schedule": crontab(minute=0, hour="9,21"),
        },
        # disabled-user-appeal-flow: 01:00 UTC = 09:00 Asia/Taipei
        "appeal-digest": {
            "task": "app.workers.appeal_digest.send_appeal_digest",
            "schedule": crontab(minute=0, hour=1),
        },
        "eval-reminder": {
            "task": "app.workers.eval_reminder.send_eval_reminder",
            "schedule": crontab(minute=0, hour=9, day_of_month=1),
        },
        "db-backup": {
            "task": "app.workers.db_backup.run_db_backup",
            "schedule": crontab(minute=0, hour=3),
        },
        # multi-provider-usage-monitoring: hourly snapshot collector +
        # daily 09:00 Taipei (= 01:00 UTC) threshold alert evaluator.
        "usage-collector": {
            "task": "app.workers.usage_collector.collect_provider_usage",
            "schedule": crontab(minute=0),
        },
        "usage-alert": {
            "task": "app.workers.usage_alert.evaluate_usage_thresholds",
            "schedule": crontab(minute=0, hour=1),
        },
    },
)
