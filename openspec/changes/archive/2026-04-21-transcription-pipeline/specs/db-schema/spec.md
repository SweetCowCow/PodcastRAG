## MODIFIED Requirements

### Requirement: episodes table

The database SHALL contain an `episodes` table storing individual episode metadata, linked to a show, including an optional reference to the audio object stored in external object storage.

#### Scenario: Episode record created

- **WHEN** an episode is inserted with a valid `show_id`
- **THEN** the record SHALL be persisted with UUID primary key, `show_id` foreign key, `title`, `description` (nullable), `audio_url`, `duration_seconds` (nullable), `published_at` (nullable), `guid` (unique per show), `audio_storage_key` (nullable VARCHAR), and `created_at`

#### Scenario: Orphan episode rejected

- **WHEN** an episode is inserted with a non-existent `show_id`
- **THEN** the database SHALL raise a foreign key constraint violation

#### Scenario: Storage key recorded after upload

- **WHEN** an episode has its audio uploaded to object storage and `audio_storage_key` is updated to the returned key
- **THEN** subsequent reads SHALL return the persisted `audio_storage_key` value without altering other columns

### Requirement: transcripts table

The database SHALL contain a `transcripts` table with a one-to-one relationship to episodes, tracking transcription status and the last error message when a transcription fails.

#### Scenario: Transcript record created

- **WHEN** a transcript is inserted for an episode
- **THEN** the record SHALL be persisted with UUID primary key, `episode_id` (unique foreign key), `status` (enum: `pending`, `processing`, `completed`, `failed`), `language` (nullable), `transcribed_at` (nullable), `error_message` (nullable TEXT), and `created_at`

#### Scenario: Duplicate transcript for episode rejected

- **WHEN** a second transcript is inserted for the same `episode_id`
- **THEN** the database SHALL raise a unique constraint violation

#### Scenario: Error message recorded on failure

- **WHEN** a transcript transitions from `processing` to `failed` with an error message up to 2000 characters
- **THEN** the `error_message` column SHALL store the message exactly and subsequent reads SHALL return the same value

## ADDED Requirements

### Requirement: Alembic migration for transcription columns

The database schema SHALL include an Alembic migration that adds `episodes.audio_storage_key` and `transcripts.error_message` columns, both nullable, without rewriting existing rows.

#### Scenario: Migration applies cleanly

- **WHEN** `alembic upgrade head` runs against a database already at the backend-api baseline
- **THEN** the migration SHALL add both columns as nullable without errors and SHALL NOT alter any other column

#### Scenario: Downgrade reverses columns

- **WHEN** `alembic downgrade -1` is run after applying the transcription migration
- **THEN** both new columns SHALL be dropped and the prior baseline schema SHALL be restored
