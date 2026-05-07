# Disaster Recovery — PodcastRAG

## 承諾（RPO / RTO）

| 指標 | 目標 |
|------|------|
| **RPO**（Recovery Point Objective）| ≤ 24 小時（每日 03:00 UTC 自動備份） |
| **RTO**（Recovery Time Objective）| ≤ 30 分鐘（從拿到備份檔到 prod 還原完成） |

所有備份**離站加密**儲存在 Cloudflare R2，跟 Zeabur 平台解耦。私鑰由管理員雙地保管，平台側完全不持有解密能力。

---

## 備份位置

- **Provider**：Cloudflare R2（S3-compatible）
- **Region**：Auto（Cloudflare 自動就近）
- **Bucket**：`podcastrag-backup`（**獨立 bucket**，不共用 audio bucket `podcastrag`，token 爆炸半徑隔離）
- **Endpoint URL**：`https://<account-id>.r2.cloudflarestorage.com`（account id 在 4 個 service env `R2_BACKUP_ENDPOINT_URL` + GHA secret 同名）
- **Key 結構**：
  ```
  daily/YYYY-MM-DD.dump.age      # 最近 7 天，每日 1 份
  weekly/YYYY-MM-DD.dump.age     # 最近 28 天的每個週日，4 份
  monthly/YYYY-MM-DD.dump.age    # 最近 365 天的每月 1 號，12 份
  ```
- **Lifecycle policy**：bucket-side 自動刪除（daily 7 天 / weekly 28 天 / monthly 365 天），app 端不需要管過期

---

## 金鑰保管

備份用 [age](https://age-encryption.org/) 公鑰加密，**runtime workers 只持有公鑰，無法解密任何過去的備份**。私鑰雙人/雙地保管降低單點失效。

### 公鑰（兩把都進加密 recipient list）

| 用途 | Public Key |
|------|------------|
| Admin recipient | `age1ww7yj4qffqz3nfc9chhpedncy5hksx25jwqnkw7pafnlp98qf46qpqls7t` |
| GHA recipient | `age1yc8utpy2hwssny6zpf9ynvcwdvmgr7r9xyts6u8jqt5cmyvq69yqwjglx8` |

兩把公鑰用逗號串接寫進 `BACKUP_AGE_PUBLIC_KEY` env（4 service：backend / worker / dispatcher / beat）。每份備份兩把私鑰任一把都能解。

### 私鑰

| 用途 | 位置 |
|------|------|
| **Admin private key** | (1) 管理員本機 `~/.config/podcastrag/backup-private-admin.key` (mode 600) (2) 密碼管理器條目「PodcastRAG Backup Private Key」 |
| **GHA private key** | (1) 管理員本機 `~/.config/podcastrag/backup-private-gha.key` (mode 600) (2) GitHub Actions repo secret `BACKUP_AGE_PRIVATE_KEY_GHA`（從 (1) 用 `gh secret set` pipe 進去，不經 chat） |

**遺失** = 23 份備份報廢；**外洩** = 全 leak。**雙地不同性質保管**降單點，admin 與 GHA 私鑰**獨立**讓 GHA 環境若被攻陷不波及本機備份。

### 關聯 Secrets / Env

**Zeabur 4 service env**（backend / worker / dispatcher / beat）：

| Env 名 | 內容 |
|--------|------|
| `R2_BACKUP_ENDPOINT_URL` | Cloudflare R2 endpoint URL |
| `R2_BACKUP_BUCKET` | `podcastrag-backup` |
| `R2_BACKUP_ACCESS_KEY_ID` | R2 Token A（write，scoped to backup bucket） |
| `R2_BACKUP_SECRET_ACCESS_KEY` | （同上） |
| `BACKUP_AGE_PUBLIC_KEY` | admin 與 GHA 兩 pub key 逗號分隔 |

**GitHub Actions repo secrets**：

| Secret 名 | 內容 |
|-----------|------|
| `R2_READONLY_KEY_ID` | R2 Token B（read-only，scoped to backup bucket） |
| `R2_READONLY_SECRET` | （同上） |
| `R2_BACKUP_ENDPOINT_URL` | 同 service env |
| `R2_BACKUP_BUCKET` | `podcastrag-backup` |
| `BACKUP_AGE_PRIVATE_KEY_GHA` | GHA 那把私鑰內容 |
| `ZSEND_API_KEY`, `ZSEND_FROM_EMAIL`, `ZSEND_ADMIN_TO_EMAIL` | 還原驗證通知信用 |

⚠️ **新增 R2 token / 換 keypair 後**：上面兩組環境變數都要同步更新，否則某一邊會崩。

---

## 還原步驟（凌晨被叫起來照做）

### 0. 工具準備

需要：`age`、`aws` CLI、`pg_restore`（postgresql client tools）。

```bash
# macOS
brew install age awscli postgresql@16
# Debian/Ubuntu
sudo apt install age awscli postgresql-client
```

### 1. 列出可用備份

```bash
export AWS_ACCESS_KEY_ID=<R2 token：可用 read-only token B>
export AWS_SECRET_ACCESS_KEY=<同上>
export AWS_DEFAULT_REGION=auto
export R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
export R2_BUCKET=podcastrag-backup

# 看每日（最近 7 天）
aws s3 ls "s3://${R2_BUCKET}/daily/"  --endpoint-url="${R2_ENDPOINT}"
# 看週度
aws s3 ls "s3://${R2_BUCKET}/weekly/" --endpoint-url="${R2_ENDPOINT}"
# 看月度
aws s3 ls "s3://${R2_BUCKET}/monthly/" --endpoint-url="${R2_ENDPOINT}"
```

### 2. 下載指定的一份

```bash
aws s3 cp "s3://${R2_BUCKET}/daily/2026-05-13.dump.age" \
  ./backup.dump.age --endpoint-url="${R2_ENDPOINT}"
```

### 3. 用 admin 私鑰解密

```bash
age --decrypt -i ~/.config/podcastrag/backup-private-admin.key \
    -o ./backup.dump ./backup.dump.age
```

成功後磁碟上會出現未加密的 `backup.dump`（custom-format pg_dump 檔）。**復原完成後立刻 `rm` 掉**，不要長期留。

### 4. Restore 到一個 fresh PG（建議：另開一個 DB 叫 `podcastrag_restore` 先驗）

```bash
createdb -h <host> -U postgres podcastrag_restore
pg_restore --no-owner --no-acl \
    -h <host> -U postgres -d podcastrag_restore \
    ./backup.dump
```

### 5. Sanity check

```bash
psql -h <host> -U postgres -d podcastrag_restore -c "
  SELECT 1 FROM pg_extension WHERE extname='vector';
  SELECT count(*) AS episodes        FROM episodes;
  SELECT count(*) AS chunks          FROM transcript_chunks;
  SELECT count(*) AS users           FROM users;
"
```

對比 `https://api.podcastrag.app/stats`：`episodes_completed` 跟 `transcript_chunks` 應該在 ±25% 之內（restore 包含所有狀態的 episodes，prod /stats 只算 transcribed，所以 restore 會略多正常）。

### 6. 若是真實 DR：把 prod DATABASE_URL 切到還原好的 DB

依當前 Zeabur 設定走 service env 改 `DATABASE_URL`、redeploy 4 service。或更換 prod PG service 為新 instance 並把 DATABASE_URL 指過去。

---

## 資料流（Mermaid）

```mermaid
flowchart LR
    PG[(Prod Postgres<br/>Zeabur)]
    Beat[Celery Beat<br/>03:00 UTC daily]
    Pipe[pg_dump | age --encrypt]
    R2[(Cloudflare R2<br/>podcastrag-backup)]
    GHA[GHA Monthly<br/>restore-verification.yml]
    Admin[Admin Manual<br/>Restore on Demand]
    ZSend[ZSend Email]

    Beat -->|trigger| Pipe
    PG -->|"pg_dump --format=custom"| Pipe
    Pipe -->|"daily/YYYY-MM-DD.dump.age"| R2
    Pipe -->|"+ weekly/ on Sun"| R2
    Pipe -->|"+ monthly/ on day 1"| R2
    Pipe -->|"failure / size anomaly"| ZSend

    R2 -->|monthly cron| GHA
    GHA -->|"pg_restore<br/>+ sanity SQL"| GHA
    GHA -->|"OK / FAILED"| ZSend

    R2 -->|on demand| Admin
```

---

## 「萬一…」應對手冊

### 私鑰遺失

- **本機 + password manager 都沒了** → 23 份備份全變廢檔，無解。立刻啟動 R3.x post-mortem。
- **本機沒了，但 password manager 還在** → 重新 `age-keygen` 一把，把 admin private key 從 password manager 還原寫回本機 `~/.config/podcastrag/backup-private-admin.key`，繼續用。**不要**為此 rotate 公鑰，否則舊備份解不開。
- **password manager 沒了，本機還在** → 立刻把本機那把貼回 password manager。

### R2 access 失效（Token leak / Cloudflare 帳號被踢）

- 走 Cloudflare dashboard 馬上 revoke leak 的 token，重發新 token，更新 4 個 service env + GHA secret。
- bucket 本身與已存備份不受影響。
- 若整個 Cloudflare 帳號失聯：手動把最近一份備份從 dashboard 下載到本機，再走「還原步驟」上面那段。

### Backup 檔案部分損毀（age decrypt 過但 pg_restore 報錯）

- `pg_restore --list backup.dump` 看 catalog 是否完整。
- 若 catalog 完整但個別 table 壞掉：用 `-L` 只 restore 健康的 sections。
- **同時往前找一份**（昨天 / 前天 / 上週日 / 上月 1 號），通常 RPO 還在 24h-30d 之間就有救。
- 觸發手動 `restore-verification.yml` 把每月 1 份再驗一輪。

### 連續多天 size anomaly 警報

- 先看 ZSend 信內容（today vs yesterday byte 數 + ratio）。
- 「驟增」 → 可能 RSS 大量 ingest（看 admin queue tab） / vector 表突然 swell（看 R3 是否在 backfill）。
- 「驟減」 → 可能 prod 表被 truncate / migration 跑壞 → **立刻拉昨日備份試 restore 確認資料還在**。

---

## 文件 sync 規則

當下列任一改變時，**同一個 commit** 必須同步更新本檔：

- bucket 名 / endpoint URL / key prefix
- 加密工具（age → 其他）
- 公鑰 / 私鑰位置 / 命名
- 還原指令的 flag
- RPO / RTO 承諾

reviewer 會擋這項一致性。
