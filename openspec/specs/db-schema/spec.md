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
### Requirement: users table

The database SHALL contain a `users` table storing per-user identity, role, status, and quota counters.

#### Scenario: User record created on first Google login

- **WHEN** a user is inserted following a Google OAuth callback
- **THEN** the row SHALL be persisted with the following columns: `id` (UUID primary key), `email` (TEXT, unique, not null), `name` (TEXT, nullable), `avatar_url` (TEXT, nullable), `provider` (TEXT, not null, default `'google'`), `google_sub` (TEXT, unique, not null when provider is `google`), `role` (TEXT, not null, CHECK constraint in `('admin', 'member')`), `status` (TEXT, not null, CHECK constraint in `('active', 'pending', 'disabled')`), `total_queries` (BIGINT, not null, default 0), `quota_remaining` (INTEGER, not null, default 100), `quota_initial` (INTEGER, not null, default 100), `notes` (TEXT, nullable), `created_at` (TIMESTAMPTZ, not null, default `now()`), `last_login_at` (TIMESTAMPTZ, nullable)

#### Scenario: Duplicate email is rejected

- **WHEN** an insert is attempted with an `email` that already exists in the table
- **THEN** the database SHALL raise a unique constraint violation

#### Scenario: Invalid role rejected

- **WHEN** an insert or update sets `role` to a value other than `'admin'` or `'member'`
- **THEN** the database SHALL raise a check constraint violation

#### Scenario: Invalid status rejected

- **WHEN** an insert or update sets `status` to a value other than `'active'`, `'pending'`, or `'disabled'`
- **THEN** the database SHALL raise a check constraint violation

<!-- @trace
source: authentication-system
updated: 2026-05-02
-->


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
-->

---
### Requirement: sessions table

The database SHALL contain a `sessions` table storing server-side session state for authenticated users.

#### Scenario: Session row created on login

- **WHEN** a user completes Google OAuth callback and a session is created
- **THEN** a row SHALL be inserted with: `id` (UUID primary key), `user_id` (UUID, foreign key to `users.id` ON DELETE CASCADE, not null), `session_token_hash` (TEXT, unique, not null, SHA-256 hex digest), `csrf_token_hash` (TEXT, not null), `created_at` (TIMESTAMPTZ, default `now()`), `expires_at` (TIMESTAMPTZ, not null), `last_seen_at` (TIMESTAMPTZ, default `now()`), `ip` (INET, nullable), `user_agent` (TEXT, nullable)

#### Scenario: Cascade delete on user removal

- **WHEN** a row in `users` is deleted
- **THEN** all rows in `sessions` whose `user_id` references that user SHALL also be deleted

#### Scenario: Session token is stored only as hash

- **WHEN** a session row is inspected
- **THEN** no plaintext session token cookie value SHALL be present in any column
- **AND** `session_token_hash` SHALL be the 64-character lowercase SHA-256 hex digest of the cookie value

<!-- @trace
source: authentication-system
updated: 2026-05-02
-->


<!-- @trace
source: authentication-system
updated: 2026-05-02
code:
  - docs/case-studies/transcription-queue-discussion.md
  - docs/case-studies/local-vs-prod-verification-violation.md
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

---
### Requirement: qa_feedback table

The database SHALL contain a `qa_feedback` table storing thumbs vote and optional comment per AI-answer interaction.

Columns:
- `id` UUID PRIMARY KEY DEFAULT gen_random_uuid()
- `query_id` VARCHAR(64) NOT NULL — opaque id assigned by the backend per RAG query response
- `user_id` UUID NOT NULL REFERENCES `users(id)` ON DELETE CASCADE
- `vote` VARCHAR(8) NOT NULL CHECK (`vote` IN ('up', 'down'))
- `comment` TEXT NULL
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()

Indexes:
- `ix_qa_feedback_query_user_created` on `(query_id, user_id, created_at DESC)` to support "latest vote per (user, query)" reads

The table SHALL be append-only: votes are inserted as new rows; existing rows SHALL NOT be updated or deleted on re-vote.

#### Scenario: Migration creates the table

- **WHEN** the Alembic migration runs
- **THEN** `qa_feedback` SHALL exist with all listed columns and the index `ix_qa_feedback_query_user_created`

#### Scenario: User deletion cascades

- **GIVEN** a user with 5 qa_feedback rows
- **WHEN** the user row is deleted
- **THEN** all 5 qa_feedback rows SHALL be removed by the cascade

#### Scenario: Invalid vote rejected by CHECK constraint

- **WHEN** an insert attempts `vote='maybe'`
- **THEN** Postgres SHALL raise a CHECK constraint violation


<!-- @trace
source: r1-ui-feedback-infra
updated: 2026-05-05
code:
  - src/LandingPage.jsx
  - backend/alembic/versions/q5f6a7b8c9d0_add_qa_feedback_and_events.py
  - src/QueryPage.jsx
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/case-studies/zeabur-platform-case-study.md
  - docs/research/competitive-analysis.md
  - docs/case-studies/transcription-queue-discussion.md
  - aisteps-tab.png
  - backend/app/schemas/event.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/api/events.py
  - backend/app/api/qa_feedback.py
  - backend/app/main.py
  - backend/app/models/qa_feedback.py
  - backend/app/core/csrf.py
  - backend/app/schemas/query.py
  - backend/app/schemas/qa_feedback.py
  - docs/case-studies/build-zeabur-pptx.js
  - backend/app/api/query.py
  - src/PodcastSelect.jsx
  - docs/research/competitive-feature-plan.md
  - docs/research/r1-rag-eval-brief.md
  - backend/app/models/event.py
  - backend/app/core/rate_limit.py
  - index.html
  - backend/app/models/__init__.py
tests:
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_qa_feedback_stats.py
  - backend/tests/test_events_api.py
-->

---
### Requirement: events table

The database SHALL contain an `events` table for general-purpose client-side event ingestion.

Columns:
- `id` UUID PRIMARY KEY DEFAULT gen_random_uuid()
- `event_type` VARCHAR(32) NOT NULL — discriminator (initial allowed value: `'citation_click'`)
- `event_payload` JSONB NOT NULL — type-specific payload, validated at the API layer
- `user_id` UUID NULL REFERENCES `users(id)` ON DELETE SET NULL — populated when the request carries a valid session
- `created_at` TIMESTAMPTZ NOT NULL DEFAULT NOW()

Indexes:
- `ix_events_type_created` on `(event_type, created_at DESC)`

The table schema SHALL allow future event types without schema migration; payload validation SHALL happen at the API layer (Pydantic schemas keyed by `event_type`).

#### Scenario: Migration creates the table

- **WHEN** the Alembic migration runs
- **THEN** `events` SHALL exist with all listed columns and the index `ix_events_type_created`

#### Scenario: Event row persists arbitrary payload as JSONB

- **WHEN** a row is inserted with `event_payload = {"query_id": "q-1", "chunk_id": "c-2", "position": 0}`
- **THEN** the row SHALL be readable back with the same JSON structure

#### Scenario: Anonymous event has NULL user_id

- **WHEN** the API inserts an event without a session-resolved user
- **THEN** the row SHALL have `user_id IS NULL`

#### Scenario: User deletion sets event user_id to NULL (preserves event row)

- **GIVEN** a user with 3 events rows
- **WHEN** the user is deleted
- **THEN** the events rows SHALL still exist
- **AND** their `user_id` SHALL be NULL

<!-- @trace
source: r1-ui-feedback-infra
updated: 2026-05-05
code:
  - src/LandingPage.jsx
  - backend/alembic/versions/q5f6a7b8c9d0_add_qa_feedback_and_events.py
  - src/QueryPage.jsx
  - docs/case-studies/dual-write-migration-defeated-by-entrypoint.md
  - docs/case-studies/zeabur-platform-case-study.md
  - docs/research/competitive-analysis.md
  - docs/case-studies/transcription-queue-discussion.md
  - aisteps-tab.png
  - backend/app/schemas/event.py
  - docs/case-studies/local-vs-prod-verification-violation.md
  - backend/app/api/events.py
  - backend/app/api/qa_feedback.py
  - backend/app/main.py
  - backend/app/models/qa_feedback.py
  - backend/app/core/csrf.py
  - backend/app/schemas/query.py
  - backend/app/schemas/qa_feedback.py
  - docs/case-studies/build-zeabur-pptx.js
  - backend/app/api/query.py
  - src/PodcastSelect.jsx
  - docs/research/competitive-feature-plan.md
  - docs/research/r1-rag-eval-brief.md
  - backend/app/models/event.py
  - backend/app/core/rate_limit.py
  - index.html
  - backend/app/models/__init__.py
tests:
  - backend/tests/test_qa_feedback_api.py
  - backend/tests/test_qa_feedback_stats.py
  - backend/tests/test_events_api.py
-->

---
### Requirement: transcript_chunks tsvector column

The `transcript_chunks` table SHALL contain a `text_tsvector` column of type `tsvector` (nullable, populated by application code after jieba tokenisation), and a GIN index `ix_chunks_text_tsvector` over that column. The column SHALL NOT be a `GENERATED` column because PostgreSQL has no built-in Chinese tokeniser and the value must be produced application-side using jieba + the custom dictionary.

#### Scenario: Column and index present after migration

- **WHEN** the `r3.1-hybrid-retrieval` Alembic migration runs
- **THEN** `transcript_chunks` SHALL have a column `text_tsvector tsvector NULL`
- **AND** an index named `ix_chunks_text_tsvector` of type GIN SHALL exist on that column

#### Scenario: tsvector populated during chunk write

- **WHEN** the chunking pipeline writes a `transcript_chunks` row
- **THEN** the row's `text_tsvector` SHALL be set to `to_tsvector('simple', '<jieba tokens joined by spaces>')` evaluated on the application side
- **AND** rows already in the table from prior runs MAY have `NULL` until the rebuild script populates them


<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->

---
### Requirement: tokenizer_custom_terms table

The database SHALL contain a `tokenizer_custom_terms` table storing user-curated entity terms used to seed jieba's tokeniser. Each row SHALL have:

- `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
- `term VARCHAR(100) NOT NULL UNIQUE`
- `weight INTEGER NOT NULL DEFAULT 100` (passed to `jieba.add_word(term, weight)`)
- `source VARCHAR(50) NOT NULL DEFAULT 'manual'` (e.g. `manual`, `seed_script`)
- `created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`
- `created_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL`

#### Scenario: Insert with default columns

- **WHEN** the application inserts a row with only `term='迪拉胖'`
- **THEN** the row SHALL be persisted with `weight=100`, `source='manual'`, and the current timestamp

#### Scenario: Duplicate term rejected by uniqueness

- **GIVEN** a row exists with `term='台通'`
- **WHEN** another insert with `term='台通'` is attempted
- **THEN** the insert SHALL fail with a unique-constraint error and the original row SHALL remain unchanged


<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->

---
### Requirement: episode_description_chunks table

The database SHALL contain an `episode_description_chunks` table storing one row per episode with non-empty cleaned description, mirroring the search-relevant fields of `transcript_chunks`. Each row SHALL have:

- `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()`
- `episode_id UUID NOT NULL UNIQUE REFERENCES episodes(id) ON DELETE CASCADE`
- `text TEXT NOT NULL` (HTML-stripped + boilerplate-stripped description)
- `text_tsvector tsvector NULL`
- `embedding vector(1536) NULL`
- `created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`
- `updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`

The table SHALL have a GIN index `ix_desc_text_tsvector` on `text_tsvector` and an `ivfflat` index `ix_desc_embedding` on `embedding` using `vector_cosine_ops` with `lists=100`.

#### Scenario: One row per episode

- **WHEN** an episode with non-empty description is indexed
- **THEN** exactly one row SHALL exist in `episode_description_chunks` for that `episode_id`
- **AND** subsequent re-indexing of the same episode SHALL UPDATE the existing row, not insert a duplicate

#### Scenario: Episode delete cascades

- **WHEN** a row in `episodes` is deleted
- **THEN** any matching `episode_description_chunks` rows SHALL be deleted automatically by the foreign-key cascade

#### Scenario: Indices present after migration

- **WHEN** the migration runs
- **THEN** indices `ix_desc_text_tsvector` (GIN) and `ix_desc_embedding` (ivfflat, lists=100, vector_cosine_ops) SHALL exist on the new table

<!-- @trace
source: r3-1-hybrid-retrieval
updated: 2026-05-08
code:
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.json
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.json
  - backend/eval/runs/r31-post/eval-this-not-that-cool-20260508T053656Z.md
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.json
  - backend/scripts/rebuild_chunks.py
  - backend/eval/runs/r31-v4-k20/eval-this-not-that-cool-20260508T060609Z.md
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.md
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.json
  - backend/eval/runs/r31-v4-k8/eval-this-not-that-cool-20260508T060724Z.md
  - backend/app/api/admin/__init__.py
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.json
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.json
  - backend/eval/runs/r31-post-v4-w30/eval-this-not-that-cool-20260508T060447Z.json
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.json
  - backend/app/services/rag.py
  - src/releaseLog.jsx
  - backend/eval/runs/r31-post-v3-w30/eval-this-not-that-cool-20260508T055624Z.md
  - backend/eval/runs/r31-post-w30/eval-this-not-that-cool-20260508T053824Z.md
  - backend/app/services/chunking.py
  - backend/eval/runs/r31-post-or-w30/eval-this-not-that-cool-20260508T054817Z.md
  - docs/roadmap.md
  - backend/scripts/build_jieba_seed_dict.py
  - backend/eval/runs/r31-post-w60/eval-this-not-that-cool-20260508T053914Z.md
tests:
  - backend/tests/test_chunking_overlap.py
  - backend/tests/test_rag_rrf.py
  - backend/tests/test_rebuild_chunks.py
-->