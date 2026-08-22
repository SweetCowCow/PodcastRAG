## MODIFIED Requirements

### Requirement: Daily Backup Job

The system SHALL run a Celery Beat task daily at 03:00 UTC that creates an encrypted, compressed snapshot of the application Postgres database and uploads it to off-site object storage. The job SHALL be idempotent — re-running on the same day MUST overwrite the day's snapshot without producing duplicates. The task SHALL execute at most once per scheduled firing: the broker MUST NOT redeliver a run that is still in progress.

#### Scenario: Successful daily backup

- **WHEN** the beat task fires at 03:00 UTC
- **THEN** the system runs `pg_dump --format=custom --compress=9 --no-acl --no-owner` against the configured `DATABASE_URL`
- **AND** encrypts the output stream with the public key from `BACKUP_AGE_PUBLIC_KEY` using `age`
- **AND** uploads the encrypted artifact to the configured R2 bucket at key `daily/YYYY-MM-DD.dump.age`
- **AND** records job result (size, duration, success) via logger and dispatches a ZSend digest if `ZSEND_API_KEY` is configured
- **AND** the task returns `{"sent_count", "size_bytes", "duration_ms", "key", "swept", "aborted_uploads", "object_count", "total_bytes", "promotion_ok"}`

#### Scenario: Long-running backup is not redelivered by the broker

- **GIVEN** the Celery app is configured with `task_acks_late=True`
- **AND** a backup run takes longer than one hour (2026-08-21 measured 7,656,611 ms)
- **WHEN** the run is in progress
- **THEN** the Redis broker MUST NOT redeliver the task to another worker
- **AND** this is guaranteed by `broker_transport_options["visibility_timeout"]` being set to 14400 seconds, overriding kombu's 3600-second default
- **AND** only one `pg_dump` process runs per scheduled firing

### Requirement: Object Storage Configuration

The system SHALL connect to a Cloudflare R2 bucket via S3-compatible API using boto3. The bucket lifecycle policy SHALL expire daily/weekly/monthly artifacts on their respective schedules AND SHALL abort incomplete multipart uploads. The system SHALL verify that the lifecycle policy was actually applied rather than assuming success, and SHALL alert only when the verification outcome changes, so that a known-unfixable failure does not generate a daily alert.

#### Scenario: Lifecycle policy applied

- **WHEN** the backup task initialises the boto3 R2 client
- **THEN** it calls `PutBucketLifecycleConfiguration` with rules:
  - Daily prefix `daily/`: expire 7 days after creation
  - Weekly prefix `weekly/`: expire 28 days after creation
  - Monthly prefix `monthly/`: expire 365 days after creation
  - Bucket-wide: abort incomplete multipart uploads 1 day after initiation
- **AND** the operation is idempotent (re-applying the same policy does not change state)

#### Scenario: Lifecycle policy read back and verified

- **WHEN** `PutBucketLifecycleConfiguration` returns without raising
- **THEN** the task calls `GetBucketLifecycleConfiguration` and compares the returned rule IDs against the four expected IDs
- **AND** the outcome (`ok` or `failed`) is persisted to the R2 key `_state/lifecycle_verify.json`
- **AND** an info log line records verification success

#### Scenario: Verification outcome changes from failing to passing

- **GIVEN** `_state/lifecycle_verify.json` records the previous outcome as `failed`
- **WHEN** the current verification passes
- **THEN** the task dispatches a ZSend email with subject `[PodcastRAG] DB backup lifecycle policy restored`
- **AND** the persisted state is updated to `ok`

#### Scenario: Verification fails for the first time

- **GIVEN** `_state/lifecycle_verify.json` records the previous outcome as `ok`, or no state object exists
- **WHEN** `GetBucketLifecycleConfiguration` raises, or any expected rule ID is missing
- **THEN** the task dispatches a ZSend email with subject `[PodcastRAG] DB backup lifecycle policy NOT applied` whose body lists expected vs actual rule IDs and any error code
- **AND** the persisted state is updated to `failed`
- **AND** the backup itself proceeds regardless (a retention defect MUST NOT prevent a backup from being taken)

#### Scenario: Verification keeps failing on subsequent days

- **GIVEN** `_state/lifecycle_verify.json` already records the outcome as `failed`
- **WHEN** verification fails again with the same outcome
- **THEN** NO email is dispatched
- **AND** a warning log line records the continuing failure
- **AND** the backup itself proceeds

#### Scenario: Lifecycle policy apply is rejected

- **WHEN** `PutBucketLifecycleConfiguration` raises `ClientError` (e.g. `AccessDenied` because the R2 API token lacks bucket-configuration permission)
- **THEN** the outcome is recorded as `failed` and the state-transition alerting rules above apply
- **AND** the exception is NOT silently swallowed into a log line alone
- **AND** the backup itself proceeds

#### Scenario: Daily artifact promoted to weekly on Sunday

- **GIVEN** today is Sunday 2026-05-10
- **WHEN** the daily backup completes successfully
- **THEN** after writing `daily/2026-05-10.dump.age`, the task copies the artifact to `weekly/2026-05-10.dump.age` using a size-aware managed copy that supports objects larger than 5 GiB
- **AND** logs the promotion

#### Scenario: Daily artifact promoted to monthly on day 1

- **GIVEN** today is the first calendar day of the month (e.g. 2026-06-01)
- **WHEN** the daily backup completes successfully
- **THEN** after writing `daily/2026-06-01.dump.age`, the task copies the artifact to `monthly/2026-06-01.dump.age` using the same size-aware managed copy

#### Scenario: Promotion of an artifact larger than 5 GiB

- **GIVEN** the daily artifact is 7.07 GiB, exceeding the 5 GiB single-request `CopyObject` limit
- **WHEN** the promotion runs
- **THEN** the managed copy transparently performs a multipart copy and completes successfully
- **AND** the destination object's size equals the source object's size

#### Scenario: Promotion failure does not fail the day's backup

- **GIVEN** the daily artifact has already been uploaded successfully
- **WHEN** the weekly or monthly copy raises `ClientError` or `BotoCoreError`
- **THEN** the task dispatches a ZSend email with subject `[PodcastRAG] DB backup promotion failed YYYY-MM-DD`
- **AND** the task does NOT raise, so Celery does NOT retry and does NOT re-run `pg_dump`
- **AND** the task result reports `promotion_ok: false` alongside the successful daily key

---

## ADDED Requirements

### Requirement: Application-Side Retention Sweep

The system SHALL enforce retention in application code after each successful backup rather than relying solely on the bucket lifecycle policy, and SHALL make the outcome of that enforcement observable. The sweep SHALL refuse to perform an unexpectedly large deletion without human review.

#### Scenario: Excess artifacts deleted

- **GIVEN** the `daily/` prefix contains 12 objects matching `daily/YYYY-MM-DD.dump.age`
- **WHEN** the retention sweep runs after a successful backup
- **THEN** the objects are sorted by the date encoded in the key, descending
- **AND** the newest 7 are retained and the remaining 5 are deleted
- **AND** an info log line records the retained count, the deleted count, and the deleted keys

#### Scenario: Retention limits per prefix

- **WHEN** the retention sweep runs
- **THEN** it retains the newest 7 objects under `daily/`, 4 under `weekly/`, and 12 under `monthly/`

#### Scenario: Oversized deletion set requires human review

- **GIVEN** the computed deletion set across all prefixes contains more than 20 objects
- **WHEN** the retention sweep runs
- **THEN** NO object is deleted
- **AND** the task dispatches a ZSend email with subject `[PodcastRAG] DB backup retention sweep needs review` whose body reports the count and the keys that would have been deleted
- **AND** the task does NOT raise

#### Scenario: Malformed keys are never deleted

- **GIVEN** the bucket contains an object whose key does not match `<prefix>/YYYY-MM-DD.dump.age` (for example `_state/lifecycle_verify.json`)
- **WHEN** the retention sweep runs
- **THEN** that object is excluded from both the retention count and the deletion set
- **AND** a warning log line records the unrecognised key

#### Scenario: Under-populated prefix is skipped entirely

- **GIVEN** a prefix contains fewer objects than its retention limit
- **WHEN** the retention sweep runs
- **THEN** no deletion is attempted for that prefix
- **AND** the sweep proceeds to the remaining prefixes

#### Scenario: Partial delete failure is treated as sweep failure

- **GIVEN** `delete_objects` returns a non-empty `Errors` array without raising (for example a per-key `AccessDenied`)
- **WHEN** the retention sweep inspects the response
- **THEN** the sweep SHALL report failure
- **AND** the task dispatches a ZSend email with subject `[PodcastRAG] DB backup retention sweep failed YYYY-MM-DD` whose body lists the failed keys and their error codes
- **AND** the successfully deleted keys are still reported in the log

#### Scenario: Sweep failure does not fail the backup

- **WHEN** any list or delete call in the sweep, or any call in the stale-multipart cleanup, raises `ClientError` or `BotoCoreError`
- **THEN** the task dispatches a ZSend email with subject `[PodcastRAG] DB backup retention sweep failed YYYY-MM-DD`
- **AND** the task does NOT raise (the day's backup is already safely uploaded)

---

### Requirement: Stale Multipart Upload Cleanup

The system SHALL abort incomplete multipart uploads left behind by interrupted backup runs, because such uploads are billed by R2 but are not returned by object listings.

#### Scenario: Stale uploads aborted

- **GIVEN** `ListMultipartUploads` returns uploads initiated more than 24 hours ago
- **WHEN** the cleanup runs after a successful backup
- **THEN** each stale upload is aborted via `AbortMultipartUpload`
- **AND** an info log line records the number aborted and their keys

#### Scenario: In-flight upload not aborted

- **GIVEN** an upload was initiated less than 24 hours ago
- **WHEN** the cleanup runs
- **THEN** that upload is left untouched

#### Scenario: No stale uploads

- **WHEN** `ListMultipartUploads` returns no `Uploads` key
- **THEN** the cleanup is a no-op and does not raise

#### Scenario: Abort failure is surfaced

- **WHEN** `AbortMultipartUpload` raises `ClientError` or `BotoCoreError` for any upload
- **THEN** the task dispatches the `[PodcastRAG] DB backup retention sweep failed YYYY-MM-DD` alert including the affected key
- **AND** the task does NOT raise

---

### Requirement: Bucket Usage Guard

The system SHALL monitor absolute bucket usage after each backup and alert when it exceeds expected bounds, so that a retention failure is detected within 24 hours instead of accumulating silently.

#### Scenario: Object count exceeds expected maximum

- **GIVEN** the retention design targets at most 23 artifacts
- **WHEN** the post-backup usage check counts more than 30 objects across `daily/`, `weekly/`, and `monthly/`
- **THEN** the task dispatches a ZSend email with subject `[PodcastRAG] DB backup bucket usage alert`
- **AND** the body reports the object count per prefix, the total byte size, and the expected maximum

#### Scenario: Total size exceeds threshold

- **WHEN** the post-backup usage check finds total bucket size above 300 GB
- **THEN** the same usage alert is dispatched with the measured total

#### Scenario: Usage within bounds

- **GIVEN** the bucket holds 23 objects totalling 163 GB
- **WHEN** the usage check runs
- **THEN** no alert is dispatched
- **AND** an info log line records the count and total size

#### Scenario: Usage check is advisory only

- **GIVEN** the usage check raises `ClientError` while listing objects
- **WHEN** the failure propagates to the task
- **THEN** the failure is logged at warning level
- **AND** no exception escapes the task
- **AND** the task result still reports the successful backup with `object_count: null` and `total_bytes: null`
