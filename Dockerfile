FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

# Default: run alembic upgrade + uvicorn (backend).
# Worker: set START_COMMAND env to `celery -A app.workers.celery_app worker --loglevel=info --concurrency=1`.
ENTRYPOINT ["/entrypoint.sh"]
