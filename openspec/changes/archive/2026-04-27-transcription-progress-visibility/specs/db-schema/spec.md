## MODIFIED Requirements

### Requirement: transcripts table

The database SHALL contain a `transcripts` table with a one-to-one relationship to episodes, tracking transcription status, the last error message when a transcription fails, and the time of the last row modification.

#### Scenario: Transcript record created

- **WHEN** a transcript is inserted for an episode
- **THEN** the record SHALL be persisted with UUID primary key, `episode_id` (unique foreign key), `status` (enum: `pending`, `processing`, `completed`, `failed`), `language` (nullable), `transcribed_at` (nullable), `error_message` (nullable TEXT), `created_at`, and `updated_at` (timestamptz non-null)

#### Scenario: Duplicate transcript for episode rejected

- **WHEN** a second transcript is inserted for the same `episode_id`
- **THEN** the database SHALL raise a unique constraint violation

#### Scenario: Error message recorded on failure

- **WHEN** a transcript transitions from `processing` to `failed` with an error message up to 2000 characters
- **THEN** the `error_message` column SHALL store the message exactly and subsequent reads SHALL return the same value

#### Scenario: updated_at refreshes on row modification

- **WHEN** any column of an existing `transcripts` row is updated (e.g. status transition, error_message assignment, transcribed_at set)
- **THEN** the `updated_at` column SHALL be set to the current UTC timestamp as part of the same UPDATE statement (via SQLAlchemy `onupdate=func.now()`)

#### Scenario: updated_at populated on insert

- **WHEN** a new `transcripts` row is inserted without an explicit `updated_at` value
- **THEN** the `updated_at` column SHALL receive the current UTC timestamp via the column's server default

#### Scenario: Existing rows backfilled during migration

- **WHEN** the migration that introduces the `updated_at` column is applied to a database containing existing `transcripts` rows
- **THEN** all existing rows SHALL receive the migration execution timestamp as their `updated_at` value (via `server_default=func.now()` applied at column creation)
- **AND** the column SHALL be declared NOT NULL

## ADDED Requirements

### Requirement: Alembic migration for transcripts.updated_at

The repository SHALL contain an Alembic migration that adds a non-null `updated_at` timestamptz column to the `transcripts` table with `server_default = now()` and backfills existing rows with the migration execution time, so deployments that already hold data apply cleanly without manual SQL.

#### Scenario: Upgrade adds the column

- **WHEN** `alembic upgrade head` runs against a database containing the prior schema
- **THEN** the `transcripts` table SHALL gain an `updated_at` column of type `timestamptz NOT NULL DEFAULT now()`
- **AND** every pre-existing `transcripts` row SHALL have `updated_at` set to a non-null timestamp

#### Scenario: Downgrade removes the column

- **WHEN** `alembic downgrade -1` is applied to the migration
- **THEN** the `updated_at` column SHALL be dropped from the `transcripts` table
- **AND** the schema SHALL match the state prior to this migration
