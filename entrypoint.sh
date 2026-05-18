#!/bin/sh
set -e

# celery-routing-and-dispatcher-fix:
# 若 START_COMMAND 是 celery worker 但沒指定 --queues，自動補預設四條
# (transcribe, topic, summary, control)。這是安全網 —— Zeabur worker
# service 的 START_COMMAND 也應該顯式帶 --queues=transcribe,topic,summary,control
# 以求清楚（見 docs/celery-queues.md）。
if [ -n "$START_COMMAND" ]; then
  # 用 word-boundary match：避免「app.workers.celery_app beat」的 workers
  # substring 被誤判成 worker subcommand（會錯把 --queues append 到 beat）
  is_celery_worker=0
  case "$START_COMMAND" in
    *celery*)
      case "$START_COMMAND" in
        *" worker "*|*" worker") is_celery_worker=1 ;;
      esac
      ;;
  esac
  if [ "$is_celery_worker" = 1 ]; then
    case "$START_COMMAND" in
      *--queues*|*"-Q "*)
        exec sh -c "$START_COMMAND"
        ;;
      *)
        echo "entrypoint: START_COMMAND is celery worker without --queues; auto-appending --queues=transcribe,topic,summary,control" >&2
        exec sh -c "$START_COMMAND --queues=transcribe,topic,summary,control"
        ;;
    esac
  fi
  exec sh -c "$START_COMMAND"
fi

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
