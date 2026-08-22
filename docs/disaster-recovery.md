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
- **保留策略**：**由 app 端每日備份後清掃**（保留最新 7 daily / 4 weekly / 12 monthly）。
  bucket lifecycle 規則仍然每日嘗試套用，但目前的 R2 API token 只有 Object 層權限，
  `PutBucketLifecycleConfiguration` 一律回 `AccessDenied` → **lifecycle 這層現在等於不存在**。
  詳見下節「如何確認保留策略生效」。
- **穩態預期**：23 份 × 約 7 GB ≈ 163 GB ≈ $2.4/月。超出即代表清掃壞了，會有告警。

---

## 如何確認保留策略生效

2026-08-22 發現保留策略從上線第一天起就沒生效過，累積到 108 份 / 472 GB（設計值 23 份 / 12 GB），
而且**沒有任何機制在看**——唯一的守門是「今天 vs 昨天」的大小比值，
而「每天多留一份」的日增幅不到 1%，永遠觸發不了。以下是現在該怎麼確認它真的在動。

### 憑證從哪來

**不要用本機的 aws cli**：本機 Keychain 裡那幾筆 `r2-backup-*` 目前仍是佔位符。
直接在 worker 容器內用容器自己的 `R2_BACKUP_*` env 跑 boto3，憑證全程不落地：

```bash
# 把腳本 base64 進去，避免引號地獄；worker service id 用 zeabur service list 查
zeabur service exec --id <worker-service-id> -i=false -- \
  sh -c "echo <base64-encoded-python> | base64 -d > /tmp/x.py && python -u /tmp/x.py"
```

> 長時間操作（例如超過 5 GiB 的 managed copy）**必須**在容器內 `nohup python -u ... > /tmp/x.log 2>&1 &`
> 背景執行再輪詢 log。`zeabur service exec` 會逾時（HTTP 524）斷線並殺掉行程，
> 中斷的上傳／複製會留下孤兒 multipart（計費但不列在物件清單裡）。2026-08-22 實地踩過。

### 三個要看的數字

```python
# 1) 物件數與容量 —— 穩態應為 23 份上下、約 163 GB
r = s3.list_objects_v2(Bucket=b, Prefix="daily/")   # weekly/ monthly/ 同法
# 2) multipart 殘留 —— 應為 0。這些不列在物件清單中但照常計費
s3.list_multipart_uploads(Bucket=b).get("Uploads", [])
# 3) lifecycle 規則 —— 目前預期是 AccessDenied（見下）
s3.get_bucket_lifecycle_configuration(Bucket=b)
```

判讀：

| 看到什麼 | 意思 |
|---|---|
| daily 超過 7 份、weekly 超過 4、monthly 超過 12 | app 端清掃沒跑或失敗 → 查 worker log 的 `retention sweep` 告警 |
| 物件數 > 30 或總量 > 300 GB | 用量守門應該已經寄信了；沒收到信代表 ZSend 也壞了 |
| multipart 殘留 > 0 且超過 24 小時 | `abort_stale_multipart_uploads` 沒跑到 |
| lifecycle 回 `AccessDenied` | **目前的已知狀態**，不是新問題。要修得把 R2 API token 從 Object Read & Write 換成 Admin Read & Write |
| lifecycle 回得出 4 條規則 | token 已升級，bucket 層防線恢復了 |

### 會寄出的告警

| 主旨 | 意思 |
|---|---|
| `DB backup lifecycle policy NOT applied` | lifecycle 套用／驗證失敗。**只在狀態改變時寄一次**，不會每天吵 |
| `DB backup lifecycle policy restored` | lifecycle 從壞變好（通常代表 token 換好了） |
| `DB backup retention sweep needs review` | 清掃想刪超過 20 份 → **什麼都沒刪**，等人確認 |
| `DB backup retention sweep failed` | 清掃列舉／刪除失敗，或 `delete_objects` 回報了逐 key 失敗 |
| `DB backup promotion failed` | weekly／monthly 促級失敗。當日 daily 仍然安全，RPO 不受影響 |
| `DB backup bucket usage alert` | 物件數 > 30 或總量 > 300 GB |

---

## 人工清掃步驟（保留策略壞掉、需要一次性清存量時）

**這是唯一的離站備份，刪除不可逆。** 以下每一步都不可跳過。

1. **完整盤點並存檔**——`list_objects_v2` 全量（記得處理分頁）＋ `list_multipart_uploads`，
   存成 `inventory_YYYY-MM-DD.json`。**這是刪除前的證據，必須先落地。**
2. **產出保留／刪除兩份清單**，人工目視：
   - 確認**最新的 monthly 與最新的 daily 都在保留清單裡**——這兩份絕不可刪
   - 確認刪除清單裡沒有不符 `<prefix>/YYYY-MM-DD.dump.age` 格式的 key
3. **刪除前驗證保留檔真的可用**：對每一份 `head_object`，再 ranged GET 前 32 bytes，
   確認開頭含 `age-encryption.org`。任一份驗不過就中止，不刪任何東西。
4. **執行刪除**（`delete_objects` 分批，每批上限 1000）。
   **務必檢查回傳的 `Errors` 陣列——這個 API 逐 key 失敗時不會拋例外。**
5. **abort 殘留的 multipart uploads**。
6. **重新盤點**確認收斂。

促級（把某份 daily 補成 weekly／monthly）要用 boto3 的 managed `s3.copy()`，
**不能用 `copy_object`**——後者單次上限 5 GiB，而現在單份 dump 已經 7 GB 以上。

最近一次執行紀錄與清單：`docs/case-studies/r2-cleanup-2026-08-22/`。

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

> 這裡用本機 aws cli 是刻意的：真 DR 要把檔案抓下來解密，本來就得在本機操作。
> 上面「如何確認保留策略生效」那類**例行檢查**則走容器內 boto3，不需要把憑證放到本機。

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
- **保留份數（7/4/12）、用量告警門檻、告警主旨字串**
- **R2 API token 的權限層級**（Object vs Admin，決定 lifecycle 那層能不能用）

reviewer 會擋這項一致性。
