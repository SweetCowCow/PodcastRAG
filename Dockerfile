FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

EXPOSE 8000

# Backend (default): run alembic migration then start uvicorn.
# Worker: set START_COMMAND env to `celery -A app.workers.celery_app worker --loglevel=info --concurrency=1`
CMD ["sh", "-c", "${START_COMMAND:-alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000}"]
