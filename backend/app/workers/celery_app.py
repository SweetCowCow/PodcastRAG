from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

if not settings.celery_broker_url:
    raise RuntimeError("CELERY_BROKER_URL 未設定")

celery_app = Celery(
    "podcastrag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks", "app.workers.cron_tick", "app.workers.lifecycle"],
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
    },
)
