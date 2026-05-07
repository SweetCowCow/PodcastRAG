## Context

PodcastRAG prod Postgres 累積資產：360+ episodes，~110K vector chunks，user accounts / sessions / quota / ai_steps / quota_requests / events / audit_log。資料 size 估算 1-2 GB（vectors 1536×4B × 110K ≈ 670 MB embeddings + 其他 metadata + JSON segments）。

當前無備份。架構單一 VPS（Linode SIN）+ Zeabur 託管 PG，無快照、無離站副本、無還原測試。R3 即將大幅 schema migration，repo 已公開有外部 contributor 風險。

stakeholder：管理員（ssweetcoww@gmail.com，亦為唯一 admin）。RPO 目標 24h（每日 cron）、RTO 30 min（明確還原步驟）。月成本上限 $5（容易吸收）。

## Goals / Non-Goals

### Goals
- 每日自動備份 + age 加密 + 離站儲存 R2，零人工介入
- 加密私鑰雙地保管（管理員本機 + password manager），私鑰遺失能容忍備份報廢，但備份 leak 不能造成資料 leak
- 月度自動還原測試（沒測過的備份等於沒備份）
- DR 文件 step-by-step 化，凌晨 3 點被叫起來也能照做還原
- 備份失敗 / size 異常 / R2 認證錯誤都立即 ZSend 警告，不要靜默掉資料

### Non-Goals
- 熱備援 / streaming replication（規模沒到）
- PITR 時間點還原（WAL archive 工程代價過大）
- Redis 備份（純 transient）
- 取代 Zeabur 平台原生 backup（即使後來啟用，本實作仍保留作為離站第二層）
- 自動金鑰輪替（v1 人工保管）

## Decisions

### Decision 1: 備份策略 = 每日 pg_dump（custom format）

**選擇**：daily Beat task → `pg_dump --format=custom --compress=9 --no-acl --no-owner`

**Why**：
- custom format 支援選擇性還原、parallel restore、內建壓縮
- `--no-acl --no-owner` 讓還原到不同 PG 環境（測試 / 災難 ephemeral instance）不會卡 grant
- `--compress=9` 對 vector 表壓縮率有限（1536-dim float 已接近隨機），但對 transcript JSON 壓縮顯著，整體預估 300-700 MB

**Alternatives considered**：
- `pg_dumpall`：含全 cluster 但夾不必要的 system catalogue，size 大且還原時相依 superuser
- `pg_basebackup` + WAL：可做 PITR 但 ops 複雜度爆炸（見 Non-Goals）
- 邏輯複製到 standby：要起第二個 PG instance，月成本 +$10-20，規模沒到

### Decision 2: 加密 = age（非 GPG / openssl）

**選擇**：[age](https://age-encryption.org/) 公鑰加密。Beat task 用公鑰加密，私鑰由管理員保管。

**Why**：
- 公鑰一條 string、私鑰一條 string，無 keyring 維運痛苦
- 設計目標就是 file-at-rest encryption，跟我們 use case 完美對齊
- 算法現代（X25519 + ChaCha20-Poly1305），audit 過
- Python 整合：用 [`pyrage`](https://pypi.org/project/pyrage/) 或 subprocess `age` binary，兩者都成熟

**Alternatives considered**：
- GPG：keyring 維運痛苦，pinentry 互動麻煩，CI 環境難用
- openssl `enc`：算法選擇容易踩雷（ECB mode、weak KDF），不如用 age 默認安全
- 不加密：DB 含 user emails / sessions hash / audit log，公開 R2 bucket 或 R2 key leak 都會 leak user data，**必須加密**

**選擇實作**：subprocess 呼叫系統 `age` binary（透過 dockerfile / VPS apt 預裝），比 `pyrage` 更輕量且免外部依賴版本管理。

### Decision 3: 儲存 = Cloudflare R2

**選擇**：Cloudflare R2 bucket，S3-compatible API，boto3 client。

**Why**：
- 跟 Zeabur 解耦：避 vendor 單點故障，真正的離站備份
- 免 egress 費用（將來還原拉檔不用付，AWS S3 拉 1GB ≈ $0.09，R2 = 0）
- $0.015/GB/月，1-2 GB × 23 份 ≈ $0.5/月
- 帳號跟現有 GitHub / Google 分離，更純粹的離站

**Alternatives considered**：
- Backblaze B2：更便宜（$0.006/GB/月）但 SDK 整合摩擦多一些
- Zeabur Object Storage：跟 Zeabur 同 provider，違反「離站」原則
- AWS S3：egress 費用高（1GB pull = $0.09），帳號設定 IAM 較複雜
- GitHub Release artifact：repo 公開 = leak user data，**直接淘汰**

### Decision 4: 保留策略 = 7 daily / 4 weekly / 12 monthly

**選擇**：
- 最近 7 天：每日保留
- 8-30 天：每週只留週日的（4 份）
- 31-365 天：每月只留 1 號的（12 份）
- > 365 天：自動刪
- 共 ≈ 23 份在線

**Why**：
- 多重時間粒度涵蓋不同情境（昨天誤刪 → 7 days；上個月 schema bug 沒發現 → monthly）
- 23 份 × ~500 MB ≈ 12 GB-month ≈ $0.18/月儲存
- 用 R2 lifecycle policy 自動執行，無需 app 端管理過期

**實作**：boto3 PutBucketLifecycleConfiguration 寫死 rules，bucket 建立時一次套用。

### Decision 5: 還原驗證 = GHA monthly + ZSend confirmation

**選擇**：每月 1 號 12:00 UTC GHA workflow：
1. 用 backup R2 SDK key（read-only）拉最新 monthly backup
2. 起 ephemeral postgres service container（pgvector image）
3. age decrypt（私鑰存 GHA secret `BACKUP_AGE_PRIVATE_KEY`）
4. pg_restore
5. 跑 sanity SQL：`SELECT count(*) FROM episodes`、`SELECT count(*) FROM transcript_chunks`、`SELECT count(*) FROM users` — 對比 prod 數字（從 prod 取，要會 fluctuate ±10% 才算正常）
6. 通過 → ZSend 「Backup verification OK YYYY-MM」；失敗 → ZSend ALERT

**Why**：
- 自動化 = 不會懶得做（人工驗證 N 個月後就會停做）
- GHA 跑 ephemeral PG 環境，不污染 prod
- 用 read-only R2 key + 私鑰只在 GHA → 私鑰 leak 風險可控（GHA secret 加密 + 限制 workflow 才能讀）

**Alternatives considered**：
- 不驗證：「沒測過的備份 = 沒備份」是業界常見的 incident root cause
- 季度驗證：頻率太低，bug 回報太晚

### Decision 6: 私鑰保管 = 管理員本機 + password manager 雙地

**選擇**：
- 公鑰：寫進 `BACKUP_AGE_PUBLIC_KEY` env（4 個 service 都設）+ commit 進 `docs/disaster-recovery.md`
- 私鑰：管理員本機 `~/.config/podcastrag/backup-private.key`（mode 600）+ password manager（1Password / Bitwarden）紙本 / 雲端 vault
- GHA 還原驗證用一份**獨立**私鑰副本存 GHA secret（不要與管理員私鑰相同 — 萬一 GHA 環境被攻陷，本機私鑰仍安全）

**Why**：
- 私鑰是 single point of failure：遺失 = 23 份備份全廢，外洩 = 全 leak
- 雙地不同性質保管（host machine + vault）降單點失敗
- GHA 用獨立 keypair = 隔離爆炸半徑

**Alternatives considered**：
- 只本機保管：本機壞掉時 = 全廢
- 寫進 git（即使加密 envelope）：repo 公開 → leak 私鑰加密過的 envelope 讓攻擊者離線爆破
- HashiCorp Vault / AWS KMS：規模沒到，多一個服務維運

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| 私鑰遺失 → 備份全廢 | 雙地保管（本機 + password manager），GHA 獨立 keypair |
| R2 認證 leak → 備份檔被刪 | R2 token 設 write-only / read-only 分離；監控 bucket size 異常驟降 → ZSend ALERT |
| pg_dump 過程鎖表影響 prod | `--format=custom` 預設用 read-only consistent snapshot，不阻塞寫入；timing 03:00 UTC 流量低 |
| Backup size 突然爆增（vector 表 swell）| Beat task 比對前後 size，>2× 觸發 ZSend ALERT 給管理員看 |
| 還原驗證跑掛 (GHA postgres service crash) | retry 1 次；2 次都掛 → ZSend ALERT，下個月再試 |
| age binary 不在 deploy image | Dockerfile 加 `apt install age`，加進 verify CI |
| ZSend 沒設定時備份成功但無人通知 | logger.info 仍寫 log；Beat task 成功路徑短，沉默是預設可接受 |

## Migration Plan

**Stage 0（前置）**：
- 建立 R2 bucket + 兩組 token（write-only for backup task / read-only for verification）
- 生成兩組 age keypair（管理員 + GHA）
- 設 4 個 service env：`R2_ENDPOINT_URL` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` / `BACKUP_AGE_PUBLIC_KEY`
- 設 GHA secrets：`BACKUP_AGE_PRIVATE_KEY_GHA` / `R2_READONLY_KEY_ID` / `R2_READONLY_SECRET`
- 管理員私鑰 + password manager 設定

**Stage 1（核心）**：
- `db_backup.py` Beat task 寫好 + 本機測試
- Dockerfile 加 `age` binary
- Deploy → beat 排程觸發 → 看第一份 backup 上 R2

**Stage 2（驗證）**：
- 第一份備份手動拉下來、用管理員私鑰 decrypt、pg_restore 到 local PG → sanity SQL → 確認流程可行
- DR 文件補上實際操作截圖 / 命令

**Stage 3（自動驗證）**：
- GHA `restore-verification.yml` 月度 workflow
- 觸發第一次手動跑（workflow_dispatch）→ 確認通

**Rollback**：本 change 純加法，無破壞性 schema 變動；rollback = 停掉 beat 排程 + 移除 task。R2 bucket 跟 secrets 留著無害。

## Open Questions

1. **Zeabur 平台原生 backup**：等管理員去 dashboard 確認是否啟用。如有，則本 change 仍進行（離站原則），但 daily 改 weekly 即可
2. **R2 bucket 命名**：`podcastrag-backup-prod` 還是 `podcastrag-backup`？簡單起見用後者
3. **size 異常 threshold**：「>2×」是先寫死，或 env-configurable？v1 寫死，太頻繁誤報再改 env
4. **要不要把 `~/.config/podcastrag/backup-private.key` 跟 `e2e-token` 同目錄管理**：看起來合理，DR 文件統一說明
