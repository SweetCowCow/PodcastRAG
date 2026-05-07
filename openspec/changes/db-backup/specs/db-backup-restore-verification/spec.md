## ADDED Requirements

### Requirement: Monthly Restore Verification

The system SHALL run an automated workflow once per calendar month that downloads the latest monthly backup artifact, decrypts it, restores it into an ephemeral Postgres instance, executes sanity SQL queries, and notifies administrators of the result. Untested backups are treated as broken backups.

#### Scenario: Verification succeeds

- **WHEN** the GitHub Actions workflow `restore-verification.yml` runs on the 1st of the month at 12:00 UTC
- **THEN** it spins up a `pgvector/pgvector:pg16` service container with empty database `podcastrag_verify`
- **AND** lists `monthly/` keys in the R2 bucket (read-only IAM token), picks the most recent
- **AND** downloads the encrypted artifact and decrypts it using the GHA-secret private key (`BACKUP_AGE_PRIVATE_KEY_GHA`)
- **AND** runs `pg_restore --no-owner --no-acl -d podcastrag_verify` against the decrypted dump
- **AND** executes the sanity SQL suite (Requirement: Sanity SQL Suite)
- **AND** dispatches a ZSend email with subject `[PodcastRAG] Backup verification OK YYYY-MM` if every check passes

#### Scenario: Decryption fails

- **WHEN** `age --decrypt` returns non-zero
- **THEN** the workflow step `Decrypt backup` exits with non-zero code
- **AND** subsequent steps are skipped except the notification step
- **AND** ZSend email subject is `[PodcastRAG] Backup verification FAILED — decrypt error`
- **AND** the body includes the workflow run URL for log inspection

#### Scenario: Restore fails

- **WHEN** `pg_restore` returns non-zero or sanity SQL counts fall outside expected ranges
- **THEN** the workflow fails with the offending step
- **AND** ZSend email subject is `[PodcastRAG] Backup verification FAILED — restore error`

### Requirement: Sanity SQL Suite

The verification workflow SHALL execute a fixed set of SQL queries against the restored database and compare results against expected ranges that scale with the live application.

#### Scenario: Row count check

- **GIVEN** the restored database
- **WHEN** the workflow runs `SELECT count(*) FROM episodes`, `SELECT count(*) FROM transcript_chunks`, `SELECT count(*) FROM users`
- **THEN** each count MUST be ≥ 1 (a totally empty restore is a failure)
- **AND** each count SHOULD be within ±10% of the prod value reported by the public `GET /stats` endpoint at the time of verification
- **AND** if any count is 0 or outside ±25%, the verification fails

##### Example: Acceptable variance

| Table              | Prod /stats | Restore count | Within ±10%? | Within ±25%? | Pass? |
| ------------------ | ----------- | ------------- | ------------ | ------------ | ----- |
| episodes           | 365         | 360           | yes          | yes          | yes   |
| transcript_chunks  | 113000      | 110200        | yes          | yes          | yes   |
| transcript_chunks  | 113000      | 50000         | no           | no           | NO    |
| users              | 12          | 11            | no (8%)      | yes          | yes (warn) |

#### Scenario: pgvector extension check

- **WHEN** the workflow runs `SELECT 1 FROM pg_extension WHERE extname='vector'`
- **THEN** the row MUST exist (a restore that loses the pgvector extension is broken)

### Requirement: Disaster Recovery Documentation

The repository SHALL include a step-by-step disaster recovery guide documenting backup location, key custody, restore commands, and stated RPO/RTO targets.

#### Scenario: New administrator follows the doc

- **GIVEN** a new administrator (not the original author) gains access to the project
- **WHEN** they read `docs/disaster-recovery.md`
- **THEN** the doc tells them
  - where backups live (R2 bucket name, region, prefixes)
  - how to obtain the private key (which password manager vault, which file path on prior admin's machine)
  - the exact shell commands to: list backups → download a specific dump → decrypt → restore to a fresh PG → verify
  - stated commitments: RPO ≤ 24h, RTO ≤ 30 min for the latest daily backup
- **AND** they can complete a dry-run restore against a local PG without asking the original author for clarification

#### Scenario: Doc kept in sync with implementation

- **WHEN** the bucket name, key prefixes, or encryption tool change
- **THEN** `docs/disaster-recovery.md` is updated in the same commit
- **AND** the change passes review (this is a process requirement enforced by reviewers, not automation)
