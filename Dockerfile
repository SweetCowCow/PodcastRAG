# Application image (EQ7 / o2-prebuilt-base-image).
#
# Derives from the prebuilt base image (OS packages + Python deps baked in),
# so this build skips apt entirely. Base is built/published by
# .github/workflows/build-base-image.yml → ghcr.io/sweetcowcow/podcastrag-base:base
# (public; no pull auth needed).
FROM ghcr.io/sweetcowcow/podcastrag-base:base

WORKDIR /app

COPY backend/requirements.txt .

# base-as-cache self-heal: the base already carries these deps, so this layer
# resolves them as already-satisfied without re-downloading large wheels
# (ctranslate2 / faster-whisper etc). If requirements.txt added a dep the base
# does not yet have, only the delta installs here. A stale base therefore costs
# build speed only — it never ships a prod image missing dependencies.
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
