#!/usr/bin/env bash
# spot VM 看門狗：被 preempt（TERMINATED）就自動 start，systemd 開機自動續跑。
# 會分辨「批次跑完 runner 自動 shutdown」（remaining=0 → 不重啟、停 VM、退出）
# 與「被 GCP 回收」（重啟）。用 nohup 跑：
#   nohup ./watchdog.sh > watchdog.log 2>&1 &
set -u
PROJECT="${GCP_PROJECT:-podcastrag}"
ZONE="${GCP_ZONE:-us-central1-a}"
VM="${GCP_VM_NAME:-batch-transcribe-l4-spot}"
POLL_SECONDS=300
LAST_REMAINING=-1

log() { echo "$(date '+%F %T') $*"; }

while true; do
  st=$(gcloud compute instances describe "$VM" --project="$PROJECT" --zone="$ZONE" \
        --format='value(status)' 2>/dev/null || echo "UNKNOWN")

  if [ "$st" = "RUNNING" ]; then
    prog=$(gcloud compute ssh "$VM" --project="$PROJECT" --zone="$ZONE" --command \
      "~/venv/bin/python ~/batch_transcribe/runner.py --progress --episodes ~/batch_transcribe/episodes.jsonl --workdir ~/batch_transcribe 2>/dev/null | head -1" 2>/dev/null || true)
    if [ -n "$prog" ]; then
      log "RUNNING $prog"
      rem=$(echo "$prog" | grep -oE 'remaining=[0-9]+' | cut -d= -f2)
      [ -n "$rem" ] && LAST_REMAINING=$rem
      if [ "$LAST_REMAINING" = "0" ]; then
        log "batch complete — stopping VM and exiting watchdog"
        gcloud compute instances stop "$VM" --project="$PROJECT" --zone="$ZONE" --quiet >/dev/null 2>&1
        exit 0
      fi
    else
      log "RUNNING (progress query failed — boot 中或 ssh 未就緒)"
    fi
  elif [ "$st" = "TERMINATED" ]; then
    if [ "$LAST_REMAINING" = "0" ]; then
      log "VM terminated after completion — exiting watchdog"
      exit 0
    fi
    log "preempted (last remaining=$LAST_REMAINING) → starting"
    if gcloud compute instances start "$VM" --project="$PROJECT" --zone="$ZONE" >/dev/null 2>&1; then
      log "start OK"
    else
      log "start FAILED（可能 spot 缺貨，下輪再試）"
    fi
  else
    log "status=$st"
  fi
  sleep "$POLL_SECONDS"
done
