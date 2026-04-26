# db-schema Specification

## Purpose

TBD - created by archiving change 'backend-api'. Update Purpose after archive.

## Requirements

### Requirement: shows table

The database SHALL contain a `shows` table storing Podcast show metadata.

#### Scenario: Show record created

- **WHEN** a show is inserted with a unique RSS feed URL
- **THEN** the record SHALL be persisted with an auto-generated UUID primary key, `title`, `description`, `rss_url`, `image_url` (nullable), `language` (nullable), and `created_at` timestamp

#### Scenario: Duplicate RSS URL rejected

- **WHEN** an insert is attempted with an `rss_url` that already exists
- **THEN** the database SHALL raise a unique constraint violation


<!-- @trace
source: backend-api
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/alembic/env.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/database.py
  - backend/alembic/script.py.mako
  - backend/docker-compose.yml
  - backend/app/main.py
  - backend/alembic.ini
  - backend/app/models/transcript_segment.py
  - backend/.dockerignore
  - backend/app/models/episode.py
  - backend/alembic/README
  - backend/app/core/__init__.py
  - backend/app/__init__.py
  - backend/app/models/show.py
  - .spectra/spectra.db
  - backend/requirements.txt
  - backend/app/models/__init__.py
  - backend/app/api/__init__.py
  - backend/Dockerfile
  - backend/.env.example
  - backend/app/core/config.py
-->

---
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


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/alembic.ini
  - backend/app/workers/tasks.py
  - backend/app/services/transcription/factory.py
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/alembic/env.py
  - backend/app/models/episode.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/api/shows.py
  - backend/app/models/show.py
  - backend/app/services/rss_parser.py
  - backend/Dockerfile
  - backend/app/workers/celery_app.py
  - backend/.dockerignore
  - backend/.env.example
  - backend/app/api/transcripts.py
  - backend/app/workers/__init__.py
  - .spectra/spectra.db
  - backend/app/schemas/episode.py
  - backend/app/schemas/transcript.py
  - backend/app/models/transcript.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/schemas/sync.py
  - backend/app/main.py
  - backend/app/services/__init__.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/__init__.py
  - backend/app/services/transcription/openai_provider.py
  - backend/docker-compose.yml
  - backend/app/core/database.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/api/health.py
  - backend/alembic/script.py.mako
  - backend/app/services/transcription/base.py
  - backend/app/workers/dispatch.py
  - backend/app/services/transcription/__init__.py
  - backend/app/api/episodes.py
  - backend/requirements.txt
  - backend/app/core/__init__.py
-->

---
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


<!-- @trace
source: transcription-progress-visibility
updated: 2026-04-27
code:
  - backend/app/api/admin.py
  - src/Shared.jsx
  - backend/alembic/versions/e3f4a5b6c7d8_add_transcripts_updated_at.py
  - backend/pytest.ini
  - backend/app/schemas/transcription_status.py
  - backend/app/api/shows.py
  - backend/app/services/transcription/openai_provider.py
  - src/AdminPage.jsx
  - src/ExternalApiStatusTab.jsx
  - backend/app/services/api_health.py
  - index.html
  - backend/app/services/rag.py
  - backend/app/schemas/api_health.py
  - backend/app/services/embedding.py
  - backend/app/models/transcript.py
tests:
  - backend/tests/__init__.py
  - backend/tests/test_api_health.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
-->

---
### Requirement: transcript_segments table with pgvector

The database SHALL contain a `transcript_segments` table storing timed text segments produced by the transcription provider. Segments SHALL NOT store vector embeddings; embeddings are stored at the chunk level in `transcript_chunks`.

#### Scenario: Segment record created

- **WHEN** a segment is inserted with a valid `transcript_id`
- **THEN** the record SHALL be persisted with UUID primary key, `transcript_id` foreign key, `start_time` (float seconds), `end_time` (float seconds), `text` (non-empty), and `speaker` (nullable)

#### Scenario: No embedding column

- **WHEN** the schema of `transcript_segments` is inspected after this change is applied
- **THEN** the table SHALL NOT contain an `embedding` column


<!-- @trace
source: rag-query
updated: 2026-04-23
code:
  - backend/alembic/versions/c1f2d3e4a5b6_add_rag_tables.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/transcripts.py
  - backend/app/services/__init__.py
  - backend/app/api/query.py
  - backend/alembic/env.py
  - backend/app/core/__init__.py
  - backend/app/models/llm_config.py
  - backend/app/services/chunking.py
  - backend/app/workers/dispatch.py
  - backend/requirements.txt
  - src/AdminPage.jsx
  - backend/app/workers/celery_app.py
  - backend/app/workers/__init__.py
  - backend/.env.example
  - backend/app/services/embedding.py
  - backend/app/services/llm_config.py
  - backend/.dockerignore
  - backend/app/api/admin.py
  - backend/app/core/database.py
  - backend/app/main.py
  - backend/app/services/rag.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/schemas/transcript.py
  - backend/app/services/transcription/base.py
  - backend/app/api/health.py
  - src/Shared.jsx
  - backend/app/schemas/admin.py
  - backend/app/core/bootstrap.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic.ini
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/app/core/config.py
  - backend/app/schemas/episode.py
  - backend/app/services/transcription/factory.py
  - backend/app/services/transcription/openai_provider.py
  - .spectra/spectra.db
  - backend/app/models/transcript.py
  - backend/app/schemas/query.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/alembic/script.py.mako
  - backend/app/models/transcript_segment.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/api/episodes.py
  - backend/Dockerfile
  - src/QueryPage.jsx
  - backend/app/api/shows.py
  - backend/app/models/transcript_chunk.py
  - backend/app/api/__init__.py
  - backend/app/models/episode.py
  - backend/app/models/show.py
  - backend/app/services/transcription/__init__.py
  - backend/docker-compose.yml
  - backend/app/services/rss_parser.py
  - backend/app/workers/tasks.py
  - backend/app/schemas/sync.py
-->

---
### Requirement: pgvector extension enabled

The database SHALL have the `vector` extension installed before any migration that references `vector` column type is applied.

#### Scenario: Migration applies successfully with pgvector

- **WHEN** Alembic migrations are run against a PostgreSQL instance with pgvector installed
- **THEN** all migrations SHALL complete without error and the `vector` column type SHALL be recognized


<!-- @trace
source: backend-api
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/alembic/env.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/database.py
  - backend/alembic/script.py.mako
  - backend/docker-compose.yml
  - backend/app/main.py
  - backend/alembic.ini
  - backend/app/models/transcript_segment.py
  - backend/.dockerignore
  - backend/app/models/episode.py
  - backend/alembic/README
  - backend/app/core/__init__.py
  - backend/app/__init__.py
  - backend/app/models/show.py
  - .spectra/spectra.db
  - backend/requirements.txt
  - backend/app/models/__init__.py
  - backend/app/api/__init__.py
  - backend/Dockerfile
  - backend/.env.example
  - backend/app/core/config.py
-->

---
### Requirement: Alembic migration baseline

The database schema SHALL be managed by Alembic, with an initial migration that creates all four core tables.

#### Scenario: Fresh migration run

- **WHEN** `alembic upgrade head` is run against an empty database
- **THEN** all four tables (`shows`, `episodes`, `transcripts`, `transcript_segments`) SHALL be created with the correct columns, constraints, and indexes

<!-- @trace
source: backend-api
updated: 2026-04-21
code:
  - backend/app/api/health.py
  - backend/app/models/transcript.py
  - backend/alembic/env.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/database.py
  - backend/alembic/script.py.mako
  - backend/docker-compose.yml
  - backend/app/main.py
  - backend/alembic.ini
  - backend/app/models/transcript_segment.py
  - backend/.dockerignore
  - backend/app/models/episode.py
  - backend/alembic/README
  - backend/app/core/__init__.py
  - backend/app/__init__.py
  - backend/app/models/show.py
  - .spectra/spectra.db
  - backend/requirements.txt
  - backend/app/models/__init__.py
  - backend/app/api/__init__.py
  - backend/Dockerfile
  - backend/.env.example
  - backend/app/core/config.py
-->

---
### Requirement: Alembic migration for transcription columns

The database schema SHALL include an Alembic migration that adds `episodes.audio_storage_key` and `transcripts.error_message` columns, both nullable, without rewriting existing rows.

#### Scenario: Migration applies cleanly

- **WHEN** `alembic upgrade head` runs against a database already at the backend-api baseline
- **THEN** the migration SHALL add both columns as nullable without errors and SHALL NOT alter any other column

#### Scenario: Downgrade reverses columns

- **WHEN** `alembic downgrade -1` is run after applying the transcription migration
- **THEN** both new columns SHALL be dropped and the prior baseline schema SHALL be restored


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/alembic/env.py
  - backend/alembic/script.py.mako
  - backend/alembic.ini
  - backend/app/models/episode.py
  - backend/app/models/transcript.py
-->

<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/alembic.ini
  - backend/app/workers/tasks.py
  - backend/app/services/transcription/factory.py
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/alembic/env.py
  - backend/app/models/episode.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/core/config.py
  - backend/app/api/shows.py
  - backend/app/models/show.py
  - backend/app/services/rss_parser.py
  - backend/Dockerfile
  - backend/app/workers/celery_app.py
  - backend/.dockerignore
  - backend/.env.example
  - backend/app/api/transcripts.py
  - backend/app/workers/__init__.py
  - .spectra/spectra.db
  - backend/app/schemas/episode.py
  - backend/app/schemas/transcript.py
  - backend/app/models/transcript.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/schemas/sync.py
  - backend/app/main.py
  - backend/app/services/__init__.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/__init__.py
  - backend/app/services/transcription/openai_provider.py
  - backend/docker-compose.yml
  - backend/app/core/database.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/api/health.py
  - backend/alembic/script.py.mako
  - backend/app/services/transcription/base.py
  - backend/app/workers/dispatch.py
  - backend/app/services/transcription/__init__.py
  - backend/app/api/episodes.py
  - backend/requirements.txt
  - backend/app/core/__init__.py
-->

---
### Requirement: Alembic migration for RAG tables

The codebase SHALL contain an Alembic migration that creates `transcript_chunks` and `llm_config` tables, seeds the singleton `llm_config` row, drops the `embedding` column from `transcript_segments`, and creates the ivfflat index on `transcript_chunks.embedding`.

#### Scenario: Upgrade creates and drops expected schema

- **WHEN** `alembic upgrade head` runs starting from the previous revision
- **THEN** `transcript_chunks` and `llm_config` SHALL exist with the columns and constraints defined above, the ivfflat index SHALL exist, the `llm_config` seed row SHALL be present, and `transcript_segments.embedding` SHALL no longer exist

#### Scenario: Downgrade restores prior schema

- **WHEN** `alembic downgrade -1` runs from this revision
- **THEN** `transcript_chunks` and `llm_config` SHALL be dropped, and `transcript_segments.embedding vector(1536)` SHALL be restored (nullable, no data)

<!-- @trace
source: rag-query
updated: 2026-04-23
code:
  - backend/alembic/versions/c1f2d3e4a5b6_add_rag_tables.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/api/transcripts.py
  - backend/app/services/__init__.py
  - backend/app/api/query.py
  - backend/alembic/env.py
  - backend/app/core/__init__.py
  - backend/app/models/llm_config.py
  - backend/app/services/chunking.py
  - backend/app/workers/dispatch.py
  - backend/requirements.txt
  - src/AdminPage.jsx
  - backend/app/workers/celery_app.py
  - backend/app/workers/__init__.py
  - backend/.env.example
  - backend/app/services/embedding.py
  - backend/app/services/llm_config.py
  - backend/.dockerignore
  - backend/app/api/admin.py
  - backend/app/core/database.py
  - backend/app/main.py
  - backend/app/services/rag.py
  - backend/app/schemas/__init__.py
  - backend/app/__init__.py
  - backend/app/schemas/transcript.py
  - backend/app/services/transcription/base.py
  - backend/app/api/health.py
  - src/Shared.jsx
  - backend/app/schemas/admin.py
  - backend/app/core/bootstrap.py
  - backend/app/services/storage.py
  - backend/alembic/README
  - backend/alembic.ini
  - backend/app/schemas/show.py
  - backend/app/models/__init__.py
  - backend/app/core/config.py
  - backend/app/schemas/episode.py
  - backend/app/services/transcription/factory.py
  - backend/app/services/transcription/openai_provider.py
  - .spectra/spectra.db
  - backend/app/models/transcript.py
  - backend/app/schemas/query.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/alembic/script.py.mako
  - backend/app/models/transcript_segment.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/api/episodes.py
  - backend/Dockerfile
  - src/QueryPage.jsx
  - backend/app/api/shows.py
  - backend/app/models/transcript_chunk.py
  - backend/app/api/__init__.py
  - backend/app/models/episode.py
  - backend/app/models/show.py
  - backend/app/services/transcription/__init__.py
  - backend/docker-compose.yml
  - backend/app/services/rss_parser.py
  - backend/app/workers/tasks.py
  - backend/app/schemas/sync.py
-->
---
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

<!-- @trace
source: transcription-progress-visibility
updated: 2026-04-27
code:
  - backend/app/api/admin.py
  - src/Shared.jsx
  - backend/alembic/versions/e3f4a5b6c7d8_add_transcripts_updated_at.py
  - backend/pytest.ini
  - backend/app/schemas/transcription_status.py
  - backend/app/api/shows.py
  - backend/app/services/transcription/openai_provider.py
  - src/AdminPage.jsx
  - src/ExternalApiStatusTab.jsx
  - backend/app/services/api_health.py
  - index.html
  - backend/app/services/rag.py
  - backend/app/schemas/api_health.py
  - backend/app/services/embedding.py
  - backend/app/models/transcript.py
tests:
  - backend/tests/__init__.py
  - backend/tests/test_api_health.py
  - backend/tests/test_status_endpoints.py
  - backend/tests/conftest.py
-->