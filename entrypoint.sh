#!/bin/sh
set -e

if [ -n "$START_COMMAND" ]; then
  exec sh -c "$START_COMMAND"
fi

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
