from celery import Celery
from celery.schedules import crontab

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
