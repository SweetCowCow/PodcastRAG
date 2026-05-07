## Why

PodcastRAG 上線一個多月，prod Postgres 累積了不可恢復的資產：360+ 集 transcript、~110K vector embeddings（embedding 重生成 = ~$30 + 數小時 OpenAI API 跑批 + RSS feed 不一定還在）、user accounts / sessions / quota state、ai_steps 設定、quota_request 流程紀錄、events / audit log。當前**沒有任何主動備份機制**，唯一防線是 Zeabur 託管 Postgres 自身的可靠度，無快照、無離站副本、無還原測試。

repo 公開後外部 contributor 進場、R3 hybrid retrieval 即將大改 schema（chunk 重定義、tsvector 欄位、guests 抽欄位）、後續 R3.2 會跑 LLM topic segmentation 一次性 backfill —— 任一階段 migration 出錯都可能損毀資料。RPO（Recovery Point Objective）目前實際上是**無上限**：失敗了就是全沒。

## What Changes

新增每日自動加密備份流程（Beat task）+ 離站對象儲存（Cloudflare R2）+ 月度自動還原驗證（GHA workflow）+ 災難復原文件，達成：

- **RPO ≤ 24h**：每日凌晨 03:00 UTC pg_dump
- **RTO ≤ 30 min**：清楚還原指令 + 驗證過的備份格式
- **加密**：age 加密 at rest（私鑰保管在管理員本機 + password manager）
- **離站**：Cloudflare R2（跟 Zeabur 解耦，避 vendor 單點故障）
- **保留策略**：daily 7 + weekly 4 + monthly 12 ≈ 23 份
- **驗證過的備份**：每月 1 次 GHA 自動拉最新 backup → ephemeral PG → restore → sanity SQL → ZSend 通知

備份流程內建 cost ceiling（pg_dump 失敗 / size 異常爆增 / R2 認證失敗都發 ZSend 警告）。月成本估算 ~$1（R2 儲存 + transfer）。

## Non-Goals

- **熱備援 / Streaming replication**：規模沒到，標準 daily snapshot 已足
- **時間點還原（PITR）**：要求 WAL archiving + 完整還原 pipeline，工程代價遠超 RPO 24h 帶來的好處，不做
- **Redis 備份**：Redis 內容（Celery broker / rate limit / throttle）皆 transient，重啟可重建
- **應用程式檔案備份**：架構上沒有 user-uploaded files；audio 都是 RSS 端外部 URL
- **Zeabur 平台原生備份取代本實作**：即使 Zeabur 之後加 backup tab，本實作仍保留 — 離站備份是真正的災難復原（vendor lock-in 風險、不被 Zeabur 帳號狀態綁住）
- **金鑰自動輪替**：v1 私鑰由管理員人工保管 + 紙本/password manager；自動輪替 P2

## Capabilities

### New Capabilities

- `db-backup-pipeline`：自動化備份建立 / 加密 / 上傳 / 保留 / 通知流程
- `db-backup-restore-verification`：定期還原測試 + 提供文件化還原步驟

### Modified Capabilities

(none)

## Impact

- Affected specs: `db-backup-pipeline`（新增）、`db-backup-restore-verification`（新增）
- Affected code:
  - New:
    - `backend/app/workers/db_backup.py` — Beat task：pg_dump → age encrypt → R2 upload → ZSend 通知
    - `backend/app/services/r2_client.py` — Cloudflare R2 boto3 client wrapper（含 lifecycle policy 套用 helper）
    - `backend/tests/test_db_backup.py` — Unit tests（mock subprocess + boto3，驗證流程 + 錯誤路徑）
    - `.github/workflows/restore-verification.yml` — 月度自動還原測試 workflow（拉 R2 latest → ephemeral PG → restore → sanity SQL → ZSend）
    - `docs/disaster-recovery.md` — DR 文件：備份位置、私鑰保管、還原 step-by-step、RPO/RTO 承諾
  - Modified:
    - `backend/app/workers/celery_app.py` — beat schedule 加 `db-backup` 條目（每日 03:00 UTC）+ `include` 加 `db_backup`
    - `backend/app/core/config.py` — settings 加 `r2_endpoint_url` / `r2_access_key_id` / `r2_secret_access_key` / `r2_bucket` / `backup_age_public_key` / `backup_retention_days_daily` / `backup_retention_weeks_weekly` / `backup_retention_months_monthly`
    - `backend/requirements.txt` — 加 `boto3`（已在）+ 確認 age encryption library 選用（`pyrage` 或 subprocess `age` binary）
    - `docs/roadmap.md` — Phase F 的 O3 條目標記為 in-progress / superseded by db-backup change
  - Removed: (none)
