#!/usr/bin/env bash
# external-transcript-bulk-import task 3.1 — GCP spot L4 VM 佈建/管理指令。
#
# 用法：
#   ./provision.sh create   # 建 spot L4 VM（us-central1、Deep Learning image、50GB）
#   ./provision.sh push     # 上傳 runner.py + episodes.jsonl + systemd unit
#   ./provision.sh start    # 安裝依賴 + 啟動 systemd 服務（spot 回收後自動續跑）
#   ./provision.sh status   # VM 狀態 + manifest 進度
#   ./provision.sh pull     # 回收 out/*.json + manifest 到本機 results/
#   ./provision.sh ssh      # 開 shell
#   ./provision.sh delete   # 刪 VM（磁碟一併刪除）
#
# 前置：gcloud auth login、專案 podcastrag、GPUS_ALL_REGIONS 配額 >= 1。
set -euo pipefail

PROJECT="${GCP_PROJECT:-podcastrag}"
ZONE="${GCP_ZONE:-us-central1-a}"
VM_NAME="${GCP_VM_NAME:-batch-transcribe-l4}"
MACHINE_TYPE="g2-standard-4"           # 內含 1x NVIDIA L4
DISK_SIZE="50GB"
IMAGE_FAMILY="common-cu129-ubuntu-2404-nvidia-580"  # Deep Learning VM（CUDA 12.9 預裝；2026-07 現存 family）
IMAGE_PROJECT="deeplearning-platform-release"
REMOTE_DIR="~/batch_transcribe"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

case "${1:-}" in
  create)
    gcloud compute instances create "$VM_NAME" \
      --project="$PROJECT" \
      --zone="$ZONE" \
      --machine-type="$MACHINE_TYPE" \
      --provisioning-model=SPOT \
      --instance-termination-action=STOP \
      --image-family="$IMAGE_FAMILY" \
      --image-project="$IMAGE_PROJECT" \
      --boot-disk-size="$DISK_SIZE" \
      --boot-disk-type=pd-balanced \
      --maintenance-policy=TERMINATE \
      --metadata="install-nvidia-driver=True"
    echo "VM 建立中。第一次開機會自動裝 NVIDIA driver（約 5 分鐘），之後再 push/start。"
    ;;
  push)
    gcloud compute scp --project="$PROJECT" --zone="$ZONE" --recurse \
      "$LOCAL_DIR/runner.py" \
      "$LOCAL_DIR/transcribe.service" \
      "$LOCAL_DIR/episodes.jsonl" \
      "$VM_NAME:$REMOTE_DIR/" || {
        echo "若目錄不存在，先建立再重試："
        gcloud compute ssh --project="$PROJECT" --zone="$ZONE" "$VM_NAME" \
          --command="mkdir -p $REMOTE_DIR/out"
        gcloud compute scp --project="$PROJECT" --zone="$ZONE" --recurse \
          "$LOCAL_DIR/runner.py" \
          "$LOCAL_DIR/transcribe.service" \
          "$LOCAL_DIR/episodes.jsonl" \
          "$VM_NAME:$REMOTE_DIR/"
      }
    ;;
  start)
    gcloud compute ssh --project="$PROJECT" --zone="$ZONE" "$VM_NAME" --command="
      set -e
      # cu129 Ubuntu image 沒有系統 pip → venv（2026-07-02 實測）
      sudo apt-get install -y -qq python3-pip python3-venv >/dev/null 2>&1 || true
      [ -d \$HOME/venv ] || python3 -m venv \$HOME/venv
      \$HOME/venv/bin/pip install --quiet faster-whisper opencc
      mkdir -p $REMOTE_DIR/out
      sudo cp $REMOTE_DIR/transcribe.service /etc/systemd/system/transcribe.service
      sudo sed -i \"s|__WORKDIR__|\$(readlink -f $REMOTE_DIR)|g; s|__USER__|\$USER|g\" /etc/systemd/system/transcribe.service
      sudo systemctl daemon-reload
      sudo systemctl enable --now transcribe.service
      systemctl status transcribe.service --no-pager | head -8
    "
    echo "已啟動。spot 被回收重開後 systemd 會自動續跑（manifest 跳過已完成集數）。"
    ;;
  status)
    gcloud compute instances describe "$VM_NAME" --project="$PROJECT" --zone="$ZONE" \
      --format="value(status)" || true
    gcloud compute ssh --project="$PROJECT" --zone="$ZONE" "$VM_NAME" \
      --command="python3 $REMOTE_DIR/runner.py --progress --workdir $REMOTE_DIR" || true
    ;;
  pull)
    mkdir -p "$LOCAL_DIR/results"
    gcloud compute scp --project="$PROJECT" --zone="$ZONE" --recurse \
      "$VM_NAME:$REMOTE_DIR/out" "$VM_NAME:$REMOTE_DIR/manifest.jsonl" \
      "$LOCAL_DIR/results/"
    echo "結果已回收到 $LOCAL_DIR/results/"
    ;;
  ssh)
    gcloud compute ssh --project="$PROJECT" --zone="$ZONE" "$VM_NAME"
    ;;
  delete)
    gcloud compute instances delete "$VM_NAME" --project="$PROJECT" --zone="$ZONE" --quiet
    ;;
  *)
    echo "用法: $0 {create|push|start|status|pull|ssh|delete}" >&2
    exit 1
    ;;
esac
