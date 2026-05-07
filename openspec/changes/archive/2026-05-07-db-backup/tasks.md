# Tasks

> Cross-reference key for analyzer / reviewer: each section header explicitly cites the design.md decisions and Non-Goals it implements. Decisions covered across all sections: Decision 1 (備份策略 = 每日 pg_dump custom format), Decision 2 (加密 = age 非 GPG/openssl), Decision 3 (儲存 = Cloudflare R2), Decision 4 (保留策略 = 7 daily / 4 weekly / 12 monthly), Decision 5 (還原驗證 = GHA monthly + ZSend confirmation), Decision 6 (私鑰保管 = 管理員本機 + password manager 雙地). Non-Goals respected: no streaming replication, no PITR, no Redis backup, no Zeabur OS as primary, no auto key rotation.

## 1. Pre-flight (manual external resource provisioning)

Implements: design Decision 3 (儲存 = Cloudflare R2), Decision 6 (私鑰保管 = 管理員本機 + password manager 雙地). Honours design Non-Goals (no Zeabur OS as primary off-site, no auto key rotation in v1).

- [x] 1.1 Create Cloudflare R2 account + bucket `podcastrag-backup`
- [x] 1.2 Create R2 token A (write-only, scoped to bucket) for backup task; record `R2_ACCESS_KEY_ID` + `R2_SECRET_ACCESS_KEY` for backend env
- [x] 1.3 Create R2 token B (read-only, scoped to bucket) for verification CI; record values for GHA secrets
- [x] 1.4 Generate age keypair A (administrator): `age-keygen -o backup-private.key`. Public key into `BACKUP_AGE_PUBLIC_KEY` env (Decision 6 — private-key-handling). Private key copied to `~/.config/podcastrag/backup-private.key` (mode 600) AND password manager vault entry "PodcastRAG Backup Private Key"
- [x] 1.5 Generate age keypair B (GHA verification): separate keypair so admin private key is never on GHA infra. Public key added as second `--recipient` in encrypt subprocess so artifacts can be decrypted by either keypair (resolves design Open Question 1)
- [x] 1.6 Set 4 service envs (backend / worker / dispatcher / beat) via Zeabur dashboard: `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET=podcastrag-backup`, `BACKUP_AGE_PUBLIC_KEY` (admin and GHA public keys, comma-separated)
- [x] 1.7 Set GHA repo secrets via `gh secret set`: `R2_READONLY_KEY_ID`, `R2_READONLY_SECRET`, `BACKUP_AGE_PRIVATE_KEY_GHA`

## 2. Settings + dependencies (Goals: per-Decision configurability)

Implements: spec Requirement "Object Storage Configuration" (config side) + design Decision 3

- [x] 2.1 Add settings fields in `backend/app/core/config.py`: `r2_endpoint_url`, `r2_access_key_id`, `r2_secret_access_key`, `r2_bucket`, `backup_age_public_key`. All `str | None` so env-not-configured local dev still boots
- [x] 2.2 Confirm `boto3` already pinned in `backend/requirements.txt` (it is — Whisper-compat path)
- [x] 2.3 Update Dockerfile to `apt install -y age` so the binary is on PATH for backend/worker images (Decision 2 — age binary install path)

## 3. R2 client wrapper — implements Requirement "Object Storage Configuration"

Implements: spec Requirement "Object Storage Configuration" (lifecycle policy enforcement)

- [x] 3.1 Create `backend/app/services/r2_client.py` exporting `get_r2_client()` factory + helper `apply_lifecycle_policy(client, bucket)` that puts the 7/28/365-day rules per Decision 4 (保留策略 = 7 daily / 4 weekly / 12 monthly). No-op when settings missing (return None client) so import-time doesn't fail in environments without R2.
- [x] 3.2 Unit test in `backend/tests/test_r2_client.py` verifying lifecycle policy JSON shape matches spec (mock boto3, assert PutBucketLifecycleConfiguration call args contain three rules with correct day counts)

## 4. Daily backup beat task — implements Requirement "Daily Backup Job" + "Encryption Key Handling"

Implements: spec Requirements "Daily Backup Job", "Encryption Key Handling" + design Decision 1 (備份策略 = 每日 pg_dump custom format), Decision 2 (加密 = age 非 GPG/openssl)

- [x] 4.1 Create `backend/app/workers/db_backup.py` with `@celery_app.task(name="app.workers.db_backup.run_db_backup", autoretry_for=(httpx.HTTPError, BotoCoreError), max_retries=2, retry_backoff=True)` decorated function `run_db_backup`
- [x] 4.2 Implement streaming pipeline (Encryption Key Handling — no plaintext on disk): `pg_dump --format=custom --compress=9 --no-acl --no-owner` → `age --encrypt --recipient $PUB` → in-memory bytes buffer → `client.upload_fileobj` to `daily/YYYY-MM-DD.dump.age`. Use subprocess.Popen with stdin/stdout PIPEs.
- [x] 4.3 Capture stderr from pg_dump and age subprocesses; on non-zero exit raise RuntimeError with truncated stderr (max 2000 chars)
- [x] 4.4 Implement Sunday→weekly promotion (Object Storage Configuration scenario): after daily upload succeeds and `datetime.utcnow().weekday() == 6`, call `client.copy_object` to `weekly/YYYY-MM-DD.dump.age`
- [x] 4.5 Implement day-1→monthly promotion (Object Storage Configuration scenario): after daily upload, if `datetime.utcnow().day == 1`, copy to `monthly/YYYY-MM-DD.dump.age`
- [x] 4.6 Add task to `celery_app.py`: `include` list and `beat_schedule` entry `"db-backup"` with `crontab(minute=0, hour=3)` (Daily Backup Job scenario — fires daily 03:00 UTC)

## 5. Failure surfacing — implements Requirement "Backup Failure Surfacing"

Implements: spec Requirement "Backup Failure Surfacing"

- [x] 5.1 Implement size anomaly detection (Backup Failure Surfacing — size deviation scenario): read previous-day artifact size via `client.head_object` on `daily/{yesterday}.dump.age`. If new/old ratio is outside [0.5, 2.0], dispatch ZSend warning email but still upload the artifact (don't skip on suspicion)
- [x] 5.2 Implement uncaught-failure alert (Backup Failure Surfacing — pg_dump fails / R2 upload fails scenarios): wrap top-level task body in try/finally; on any exception dispatch ZSend ALERT email with traceback summary BEFORE re-raising for Celery to record failure
- [x] 5.3 ZSend-not-configured graceful no-op: backup completes, single info log line, no failure
- [x] 5.4 Use subject templates from spec exactly: `[PodcastRAG] DB backup FAILED YYYY-MM-DD` / `[PodcastRAG] DB backup size anomaly YYYY-MM-DD`

## 6. Backup beat task — tests

Implements: validation of all four "db-backup-pipeline" Requirements

- [x] 6.1 Unit tests in `backend/tests/test_db_backup.py` happy path (Daily Backup Job): mock subprocess (pg_dump returns canned bytes), mock age (passthrough), mock boto3 client. Assert: upload called with right key `daily/YYYY-MM-DD.dump.age`; lifecycle applied on first run; Sunday promotion fires only on Sunday (Object Storage Configuration); monthly promotion fires only on day 1
- [x] 6.2 Failure-path tests (Backup Failure Surfacing): pg_dump exit 1 → RuntimeError raised + ZSend send_email called with ALERT subject; size anomaly (mock head_object → 100 MB; new artifact 500 MB) → both upload AND warning email called
- [x] 6.3 Encryption stream-only test (Encryption Key Handling — no plaintext on disk): patch tempfile / Path.write_bytes to record any disk writes; assert the test run produces zero plaintext files

## 7. Restore verification GHA — implements Requirement "Monthly Restore Verification" + "Sanity SQL Suite"

Implements: spec Requirements "Monthly Restore Verification", "Sanity SQL Suite" + design Decision 5 (還原驗證 = GHA monthly + ZSend confirmation)

- [x] 7.1 Create `.github/workflows/restore-verification.yml` with `workflow_dispatch` + `schedule: cron("0 12 1 * *")` triggers
- [x] 7.2 Job uses `pgvector/pgvector:pg16` postgres service. Steps: install age via apt → list latest monthly key via aws-cli (`aws s3 ls s3://$BUCKET/monthly/ --endpoint-url=$R2_ENDPOINT`) → download → decrypt with `$BACKUP_AGE_PRIVATE_KEY_GHA` GHA secret → `pg_restore --no-owner --no-acl -d podcastrag_verify` → run sanity SQL via psql
- [x] 7.3 Implement Sanity SQL Suite (spec Requirement "Sanity SQL Suite"): count `episodes`, `transcript_chunks`, `users`; ≥ 1 each (else fail) AND within ±25% of values fetched live from `https://api.podcastrag.app/stats` (else fail). Also `SELECT 1 FROM pg_extension WHERE extname='vector'` must return row (pgvector extension check)
- [x] 7.4 Notification step (Monthly Restore Verification — verification succeeds / decrypt fails / restore fails scenarios): always-run step that on success curls ZSend `[PodcastRAG] Backup verification OK YYYY-MM`; on failure curls ZSend `[PodcastRAG] Backup verification FAILED — <step>` with run URL

## 8. Disaster recovery documentation — implements Requirement "Disaster Recovery Documentation"

Implements: spec Requirement "Disaster Recovery Documentation"

- [x] 8.1 Create `docs/disaster-recovery.md` covering all "Disaster Recovery Documentation" scenario points: (a) overview + RPO ≤ 24h / RTO ≤ 30 min commitments, (b) backup location (R2 bucket name, region, prefixes), (c) key custody (where private keys live, password manager vault entry name, GHA secret name), (d) restore step-by-step (5 shell blocks: aws cli list → download → age decrypt → pg_restore → verify), (e) "what if" scenarios: lost private key / lost R2 access / partial corruption
- [x] 8.2 Add data-flow diagram (mermaid): prod PG → beat task → age encrypt → R2 → split (GHA monthly verify + admin manual restore on demand)
- [x] 8.3 Update `docs/roadmap.md` Phase F O3 entry: mark superseded by db-backup change

## 9. Manual end-to-end smoke

- [x] 9.1 Manually trigger `run_db_backup` (one-off Celery call): verify R2 has artifact at `daily/{today}.dump.age`
- [x] 9.2 Pull artifact locally, decrypt with administrator private key, `pg_restore` into local PG, run sanity SQL: episodes count matches prod ±10%
- [x] 9.3 Manually trigger `restore-verification.yml` (`gh workflow run "restore verification"`); verify ZSend OK email arrives
- [x] 9.4 Pause beat schedule briefly, simulate failure (set `BACKUP_AGE_PUBLIC_KEY=""` temporarily) → resume → verify ALERT email arrives → restore valid env

## 10. Stage gate / archive

- [x] 10.1 Run full backend pytest: 100% pre-existing tests pass + new `test_db_backup.py` + `test_r2_client.py` green
- [x] 10.2 Lint / format pass on new modules
- [x] 10.3 Commit + push (gitleaks pre-check). Change goes through PR for self-review
- [x] 10.4 Wait for first scheduled (not manual) beat run + first scheduled GHA verification → both green → archive db-backup with release log v1.3 entry "離線備份上線 — 24h RPO / 30min RTO"
