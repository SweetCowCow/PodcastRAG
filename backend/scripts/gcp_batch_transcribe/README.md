# GCP 批次轉錄工具組（external-transcript-bulk-import）

塞掐 Side Chat + 台灣通勤第一品牌共 1001 集 / 963 小時歷史音檔，用 GCP spot
L4 VM + faster-whisper large-v3-turbo 外部轉錄後匯入 prod。設計決策見
`openspec/changes/external-transcript-bulk-import/design.md`（D4：VM 只轉錄、
匯入從本機執行，prod 憑證不上 VM）。

## 檔案

| 檔案 | 跑在哪 | 用途 |
|------|--------|------|
| `provision.sh` | 本機 | VM 建立/上傳/啟動/監控/回收/刪除 |
| `runner.py` | VM（或本機冒煙） | 批次轉錄，manifest 續跑，完成自動關機 |
| `transcribe.service` | VM | systemd 範本：spot 回收重開自動續跑 |
| `export_episode_list.py` | 本機 | 從 prod API 匯出 episodes.jsonl |
| `import_results.py` | 本機 | 節流匯入結果到 prod（併發 ≤2） |

## SOP

```bash
cd backend/scripts/gcp_batch_transcribe

# 0) 前置：兩節目已在 prod 建好 + sync episodes（不建 schedule！）
#    gcloud auth login 已完成、GPUS_ALL_REGIONS 配額 >= 1

# 1) 匯出集數清單（略過已轉錄集數）
python3 export_episode_list.py --e2e-login \
  --show-id <塞掐-show-uuid> --show-id <台通-show-uuid>

# 2) 本機冒煙（不開 VM、零費用）——驗 schema 與續跑
python3 runner.py --episodes episodes.jsonl --workdir /tmp/smoke \
  --device cpu --compute-type int8 --model small --limit 1

# 3) 開 VM → 上傳 → 啟動（費用 gate：先 --limit 跑 1 小時樣本實測 RTF）
./provision.sh create   # spot g2-standard-4 (L4)，us-central1-a
./provision.sh push
./provision.sh start    # systemd enable --now；spot 回收自動續跑

# 4) 監控（隨時可跑；VM 被回收時 describe 會顯示 TERMINATED→自動重開）
./provision.sh status   # manifest 進度 + RTF + ETA

# 5) 跑完（runner 自動 shutdown）→ 回收結果
./provision.sh pull     # results/out/*.json + manifest.jsonl

# 6) 匯入 prod（下游成本 gate 通過後）——先試水 5 集
python3 import_results.py --results-dir results/out --e2e-login --limit 5
#    Jacky 拍板後全量：
python3 import_results.py --results-dir results/out --e2e-login
python3 import_results.py --results-dir results/out --e2e-login --retry-failed

# 7) 刪 VM + 記 actual 費用
./provision.sh delete
```

## 注意

- **匯入期間該 show 不可有 enabled schedule**（D2 時序 SOP）；全量匯入驗收
  完才建 schedule。
- **不要在匯入期間於 admin 按「重新轉錄」**——會走 whisper-1 花錢。
- runner 防幻覺參數：`condition_on_previous_text=False` + `vad_filter=True`
  （E407 pilot 實測），不要拿掉。
- spot 被回收：systemd `Restart=always` + manifest 續跑，不用人工介入；
  若整區缺貨太久，改 `--provisioning-model=STANDARD`（on-demand，費用仍 < $20）。
- e2e token 在 `~/.config/podcastrag/e2e-token`，全程不印到 stdout / chat。
