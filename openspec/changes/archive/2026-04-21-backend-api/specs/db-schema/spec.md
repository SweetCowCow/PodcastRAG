## ADDED Requirements

### Requirement: shows table

The database SHALL contain a `shows` table storing Podcast show metadata.

#### Scenario: Show record created

- **WHEN** a show is inserted with a unique RSS feed URL
- **THEN** the record SHALL be persisted with an auto-generated UUID primary key, `title`, `description`, `rss_url`, `image_url` (nullable), `language` (nullable), and `created_at` timestamp

#### Scenario: Duplicate RSS URL rejected

- **WHEN** an insert is attempted with an `rss_url` that already exists
- **THEN** the database SHALL raise a unique constraint violation

### Requirement: episodes table

The database SHALL contain an `episodes` table storing individual episode metadata, linked to a show.

#### Scenario: Episode record created

- **WHEN** an episode is inserted with a valid `show_id`
- **THEN** the record SHALL be persisted with UUID primary key, `show_id` foreign key, `title`, `description` (nullable), `audio_url`, `duration_seconds` (nullable), `published_at` (nullable), `guid` (unique per show), and `created_at`

#### Scenario: Orphan episode rejected

- **WHEN** an episode is inserted with a non-existent `show_id`
- **THEN** the database SHALL raise a foreign key constraint violation

### Requirement: transcripts table

The database SHALL contain a `transcripts` table with a one-to-one relationship to episodes, tracking transcription status.

#### Scenario: Transcript record created

- **WHEN** a transcript is inserted for an episode
- **THEN** the record SHALL be persisted with UUID primary key, `episode_id` (unique foreign key), `status` (enum: `pending`, `processing`, `completed`, `failed`), `language` (nullable), `transcribed_at` (nullable), and `created_at`

#### Scenario: Duplicate transcript for episode rejected

- **WHEN** a second transcript is inserted for the same `episode_id`
- **THEN** the database SHALL raise a unique constraint violation

### Requirement: transcript_segments table with pgvector

The database SHALL contain a `transcript_segments` table storing timed text segments with optional vector embeddings for semantic search.

#### Scenario: Segment record created

- **WHEN** a segment is inserted with a valid `transcript_id`
- **THEN** the record SHALL be persisted with UUID primary key, `transcript_id` foreign key, `start_time` (float seconds), `end_time` (float seconds), `text` (non-empty), `speaker` (nullable), and `embedding` (nullable `vector(1536)`)

#### Scenario: Vector similarity search executes

- **WHEN** a cosine similarity query is run against `transcript_segments.embedding` using pgvector operators
- **THEN** the query SHALL return results ordered by semantic similarity without error

### Requirement: pgvector extension enabled

The database SHALL have the `vector` extension installed before any migration that references `vector` column type is applied.

#### Scenario: Migration applies successfully with pgvector

- **WHEN** Alembic migrations are run against a PostgreSQL instance with pgvector installed
- **THEN** all migrations SHALL complete without error and the `vector` column type SHALL be recognized

### Requirement: Alembic migration baseline

The database schema SHALL be managed by Alembic, with an initial migration that creates all four core tables.

#### Scenario: Fresh migration run

- **WHEN** `alembic upgrade head` is run against an empty database
- **THEN** all four tables (`shows`, `episodes`, `transcripts`, `transcript_segments`) SHALL be created with the correct columns, constraints, and indexes
