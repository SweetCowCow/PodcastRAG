#!/bin/sh
set -e

# celery-routing-and-dispatcher-fix:
# 若 START_COMMAND 是 celery worker 但沒指定 --queues，自動補預設四條
# (transcribe, topic, summary, control)。這是安全網 —— Zeabur worker
# service 的 START_COMMAND 也應該顯式帶 --queues=transcribe,topic,summary,control
# 以求清楚（見 docs/celery-queues.md）。
if [ -n "$START_COMMAND" ]; then
  case "$START_COMMAND" in
    *celery*worker*)
      case "$START_COMMAND" in
        *--queues*|*-Q\ *)
          # 已顯式帶 queue，照原樣跑
          exec sh -c "$START_COMMAND"
          ;;
        *)
          echo "entrypoint: START_COMMAND is celery worker without --queues; auto-appending --queues=transcribe,topic,summary,control" >&2
          exec sh -c "$START_COMMAND --queues=transcribe,topic,summary,control"
          ;;
      esac
      ;;
    *)
      exec sh -c "$START_COMMAND"
      ;;
  esac
fi

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
