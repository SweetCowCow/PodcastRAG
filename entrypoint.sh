#!/bin/sh
set -e

# celery-routing-and-dispatcher-fix: 4-queue 模型上線後，worker 必須訂閱
# transcribe / topic / summary / control 四條 queue，否則 task 會永遠卡在
# broker 拿不到 consumer。若 START_COMMAND 是 celery worker 但沒帶
# --queues / -Q 旗標，這裡預設補上四條 queue；env 已自帶就尊重使用者覆寫。
if [ -n "$START_COMMAND" ]; then
  case "$START_COMMAND" in
    *"celery"*"worker"*)
      case "$START_COMMAND" in
        *"--queues"*|*" -Q "*|*" -Q="*)
          exec sh -c "$START_COMMAND"
          ;;
        *)
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
