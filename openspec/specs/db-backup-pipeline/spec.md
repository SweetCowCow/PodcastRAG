# db-backup-pipeline Specification

## Purpose

TBD - created by archiving change 'db-backup'. Update Purpose after archive.

## Requirements

### Requirement: Daily Backup Job

The system SHALL run a Celery Beat task daily at 03:00 UTC that creates an encrypted, compressed snapshot of the application Postgres database and uploads it to off-site object storage. The job SHALL be idempotent — re-running on the same day MUST overwrite the day's snapshot without producing duplicates.

#### Scenario: Successful daily backup

- **WHEN** the beat task fires at 03:00 UTC
- **THEN** the system runs `pg_dump --format=custom --compress=9 --no-acl --no-owner` against the configured `DATABASE_URL`
- **AND** encrypts the output stream with the public key from `BACKUP_AGE_PUBLIC_KEY` using `age`
- **AND** uploads the encrypted artifact to the configured R2 bucket at key `daily/YYYY-MM-DD.dump.age`
- **AND** records job result (size, duration, success) via logger and dispatches a ZSend digest if `ZSEND_API_KEY` is configured
- **AND** the task returns `{"sent_count", "size_bytes", "duration_ms"}`

#### Scenario: ZSend not configured

- **WHEN** the beat task fires
- **AND** either `ZSEND_API_KEY` or `ZSEND_ADMIN_TO_EMAIL` is empty
- **THEN** the backup still runs to completion
- **AND** a single info log line records "eval_reminder: ZSend not configured — skipping notification"
- **AND** the task does not raise an error

#### Scenario: Re-run on same day overwrites

- **GIVEN** an existing object at `daily/2026-05-07.dump.age` with size 412 MB
- **WHEN** the beat task fires later the same UTC day (manual trigger)
- **THEN** the new artifact replaces the old one at the same key
- **AND** R2 versioning is NOT used (single-version overwrite is intentional to keep retention math predictable)

---
### Requirement: Object Storage Configuration

The system SHALL connect to a Cloudflare R2 bucket via S3-compatible API using boto3. The bucket lifecycle policy SHALL automatically transition daily snapshots to weekly+monthly retention tiers and delete artifacts older than 365 days.

#### Scenario: Lifecycle policy applied

- **WHEN** the backup task initialises the boto3 R2 client and detects no lifecycle policy on the bucket
- **THEN** it calls `PutBucketLifecycleConfiguration` with rules:
  - Daily prefix `daily/`: expire 7 days after creation
  - Weekly prefix `weekly/`: expire 28 days after creation
  - Monthly prefix `monthly/`: expire 365 days after creation
- **AND** the operation is idempotent (re-applying the same policy does not change state)

#### Scenario: Daily artifact promoted to weekly on Sunday

- **GIVEN** today is Sunday 2026-05-10
- **WHEN** the daily backup completes successfully
- **THEN** after writing `daily/2026-05-10.dump.age`, the task additionally copies the same artifact to `weekly/2026-05-10.dump.age`
- **AND** logs the promotion

#### Scenario: Daily artifact promoted to monthly on day 1

- **GIVEN** today is the first calendar day of the month (e.g. 2026-06-01)
- **WHEN** the daily backup completes successfully
- **THEN** after writing `daily/2026-06-01.dump.age`, the task additionally copies the same artifact to `monthly/2026-06-01.dump.age`

---
### Requirement: Backup Failure Surfacing

The system SHALL alert administrators when the backup pipeline fails or produces an artifact with abnormal size, instead of failing silently.

#### Scenario: pg_dump fails

- **WHEN** the `pg_dump` subprocess exits with non-zero return code
- **THEN** the task captures stderr (truncated to 2000 chars)
- **AND** dispatches a ZSend email with subject `[PodcastRAG] DB backup FAILED YYYY-MM-DD`
- **AND** the task raises `RuntimeError` so Celery records the failure
- **AND** Celery autoretry runs at most 2 retries with exponential backoff before giving up

#### Scenario: R2 upload fails

- **WHEN** the boto3 `upload_fileobj` call raises a `BotoCoreError` or `ClientError`
- **THEN** the task captures the error class + message
- **AND** dispatches the same alert email format as pg_dump failure
- **AND** Celery autoretry applies (transient network errors recoverable)

#### Scenario: Backup size deviates significantly

- **WHEN** the encrypted artifact's byte size is more than 2× or less than 0.5× the previous successful day's size
- **THEN** the task still uploads the artifact (don't skip on suspicion)
- **AND** dispatches a ZSend email with subject `[PodcastRAG] DB backup size anomaly YYYY-MM-DD`
- **AND** the body includes today's size, yesterday's size, and the ratio
- **AND** logger.warning records the anomaly

##### Example: Anomaly thresholds

| Yesterday size | Today size | Trigger? | Reason |
| -------------- | ---------- | -------- | ------ |
| 412 MB | 850 MB | yes (>2×) | runaway growth |
| 412 MB | 180 MB | yes (<0.5×) | possible truncation |
| 412 MB | 470 MB | no | normal growth |
| 412 MB | 380 MB | no | minor compression variance |

---
### Requirement: Encryption Key Handling

The backup pipeline SHALL never persist the unencrypted dump to disk and SHALL use the public-key half of an age keypair so the runtime workers cannot decrypt past backups.

#### Scenario: Stream encryption (no plaintext on disk)

- **WHEN** the backup task runs
- **THEN** `pg_dump` stdout is piped directly into `age --encrypt --recipient $BACKUP_AGE_PUBLIC_KEY` stdin via subprocess.PIPE chain
- **AND** the encrypted bytes are streamed to boto3 `upload_fileobj` via a buffered file-like object
- **AND** at no point is a plaintext `.dump` file written to the filesystem

#### Scenario: Worker cannot decrypt

- **GIVEN** the worker container has only `BACKUP_AGE_PUBLIC_KEY` env set, not the private key
- **WHEN** anyone with worker shell access attempts `age --decrypt` on a downloaded artifact
- **THEN** the operation fails with "no identities provided"
- **AND** the only way to decrypt is using the offline-stored private key (administrator's machine + password manager copy)
