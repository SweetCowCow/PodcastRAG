FROM python:3.12-slim

WORKDIR /app

# Cache apt package downloads across builds (BuildKit cache mounts).
# sharing=locked avoids concurrent-build corruption on the shared cache.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends build-essential ffmpeg age postgresql-client

COPY backend/requirements.txt .

# Cache pip downloads across builds so repeat installs skip network fetch.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY backend/ .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# Default: run alembic upgrade + uvicorn (backend).
# Worker:     set START_COMMAND=`celery -A app.workers.celery_app worker --loglevel=info --concurrency=1`
# Dispatcher: set START_COMMAND=`python -m app.workers.dispatcher`
# Beat:       set START_COMMAND=`celery -A app.workers.celery_app beat --loglevel=info`
ENTRYPOINT ["/entrypoint.sh"]
