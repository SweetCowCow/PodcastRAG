import uuid

from app.workers.celery_app import celery_app


def enqueue_transcription(episode_id: uuid.UUID) -> str:
    result = celery_app.send_task(
        "app.workers.tasks.transcribe_episode", args=[str(episode_id)]
    )
    return result.id
