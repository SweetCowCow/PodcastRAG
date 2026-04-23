# transcription-pipeline Specification

## Purpose

TBD - created by archiving change 'transcription-pipeline'. Update Purpose after archive.

## Requirements

### Requirement: TranscriptionProvider abstraction

The backend SHALL expose an abstract `TranscriptionProvider` interface with an async `transcribe(audio_path, language)` method returning a `TranscriptionResult` that contains the full text and a list of timed segments, and SHALL provide two concrete implementations: an OpenAI Whisper API provider and a local faster-whisper provider.

#### Scenario: Provider selected by configuration

- **WHEN** the application reads `TRANSCRIPTION_PROVIDER=openai` from environment
- **THEN** `get_provider()` SHALL return an `OpenAIWhisperProvider` instance configured with the `OPENAI_API_KEY` setting

#### Scenario: Local provider selected

- **WHEN** the application reads `TRANSCRIPTION_PROVIDER=faster-whisper`
- **THEN** `get_provider()` SHALL return a `FasterWhisperProvider` instance configured with `FASTER_WHISPER_MODEL_SIZE` and `FASTER_WHISPER_COMPUTE_TYPE`

#### Scenario: Unknown provider rejected

- **WHEN** the application starts with `TRANSCRIPTION_PROVIDER=unknown`
- **THEN** configuration validation SHALL raise an error before any request is served


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/app/services/transcription/__init__.py
  - backend/app/services/transcription/base.py
  - backend/app/services/transcription/factory.py
  - backend/app/services/transcription/openai_provider.py
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/core/config.py
  - backend/.env.example
  - backend/requirements.txt
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
### Requirement: Transcribe episode endpoint

The backend SHALL expose `POST /episodes/{episode_id}/transcribe` that upserts the `transcripts` row to status `pending`, enqueues a background transcription task, and returns HTTP 202 with the transcript id and queued timestamp.

#### Scenario: Valid episode queued

- **WHEN** the endpoint is called with an existing `episode_id` and no transcript is currently processing
- **THEN** the response SHALL be HTTP 202 with a JSON body containing `transcript_id`, `status="pending"`, and `queued_at`, and a Celery task SHALL be enqueued

#### Scenario: Episode not found

- **WHEN** the endpoint is called with a non-existent `episode_id`
- **THEN** the response SHALL be HTTP 404

#### Scenario: Concurrent transcription rejected

- **WHEN** the endpoint is called for an episode whose transcript is already in `processing` status
- **THEN** the response SHALL be HTTP 409 and no new task SHALL be enqueued


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/app/api/transcripts.py
  - backend/app/main.py
  - backend/app/models/transcript.py
  - backend/app/models/episode.py
  - backend/app/schemas/transcript.py
  - backend/app/workers/dispatch.py
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
### Requirement: Get transcript endpoint

The backend SHALL expose `GET /episodes/{episode_id}/transcript` returning the transcription status, timestamps, error message (if any), and ordered segments.

#### Scenario: Completed transcript returned

- **WHEN** the endpoint is called for an episode whose transcript status is `completed`
- **THEN** the response SHALL be HTTP 200 with `status="completed"`, `language`, `transcribed_at`, and a `segments` array sorted by `start_time` ascending

#### Scenario: Pending transcript returned

- **WHEN** the endpoint is called for an episode whose transcript status is `pending` or `processing`
- **THEN** the response SHALL be HTTP 200 with the current status, empty `segments` array, and `error_message=null`

#### Scenario: Failed transcript returned

- **WHEN** the endpoint is called for an episode whose transcript status is `failed`
- **THEN** the response SHALL be HTTP 200 with `status="failed"` and a non-null `error_message`

#### Scenario: No transcript yet

- **WHEN** the endpoint is called for an episode that has never been transcribed
- **THEN** the response SHALL be HTTP 404


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/app/api/transcripts.py
  - backend/app/models/transcript.py
  - backend/app/models/transcript_segment.py
  - backend/app/schemas/transcript.py
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
### Requirement: Batch transcribe endpoint

The backend SHALL expose `POST /shows/{show_id}/transcribe-all` that enqueues transcription tasks for every episode of the show that has no transcript or whose transcript status is `failed`, and returns the count of episodes queued.

#### Scenario: Batch enqueue succeeds

- **WHEN** the endpoint is called for a show with 3 episodes where none have transcripts
- **THEN** the response SHALL be HTTP 202 with `{queued: 3}` and 3 Celery tasks SHALL be enqueued

#### Scenario: Already completed episodes skipped

- **WHEN** the endpoint is called for a show where all episodes have `status="completed"` transcripts
- **THEN** the response SHALL be HTTP 202 with `{queued: 0}` and no tasks SHALL be enqueued

#### Scenario: Show not found

- **WHEN** the endpoint is called with a non-existent `show_id`
- **THEN** the response SHALL be HTTP 404


<!-- @trace
source: transcription-pipeline
updated: 2026-04-21
code:
  - backend/app/api/transcripts.py
  - backend/app/models/show.py
  - backend/app/models/episode.py
  - backend/app/models/transcript.py
  - backend/app/workers/dispatch.py
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
### Requirement: Transcribe episode worker task

The backend SHALL define a Celery task `transcribe_episode(episode_id)` that sets transcript status to `processing`, ensures the audio file is stored in object storage, invokes the configured provider, persists segments, builds chunks and embeddings for RAG, and sets the final status to `completed` or `failed`.

#### Scenario: Successful transcription

- **WHEN** the task is dispatched for an episode with a reachable `audio_url`, a working transcription provider, and a working OpenAI embeddings API
- **THEN** the transcript SHALL end with `status="completed"`, `error_message=null`, `transcribed_at` set to the current UTC time, `transcript_segments` SHALL contain one row per segment returned by the provider, and `transcript_chunks` SHALL contain one row per chunk built from those segments with a non-null 1536-dim `embedding`

#### Scenario: Audio download failure

- **WHEN** the task cannot download the audio from `audio_url` and no prior `audio_storage_key` exists
- **THEN** the transcript SHALL end with `status="failed"` and `error_message` SHALL describe the download failure

#### Scenario: Provider error

- **WHEN** the provider raises an exception during transcription
- **THEN** the transcript SHALL end with `status="failed"`, `error_message` SHALL contain the exception message (truncated to 2000 characters), the Celery task SHALL not auto-retry, and no `transcript_chunks` rows SHALL be created for this transcript

#### Scenario: Embedding API failure fails the transcript

- **WHEN** segments persist successfully but the embeddings API raises an exception while building chunks
- **THEN** the transcript SHALL end with `status="failed"`, `error_message` SHALL contain the exception message (truncated to 2000 characters), and no `transcript_chunks` rows SHALL be left behind for this transcript

#### Scenario: Audio reused across transcriptions

- **WHEN** the task runs for an episode that already has a non-null `audio_storage_key`
- **THEN** the task SHALL download the audio from object storage and SHALL NOT fetch `audio_url` again

#### Scenario: Re-transcription replaces chunks

- **WHEN** the task runs for an episode whose `transcript_chunks` rows already exist from a prior run
- **THEN** the task SHALL delete the existing chunks (via the cascade triggered by transcript row recreation, or by an explicit delete) before inserting new chunks, so the final state contains only chunks from the current run


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
### Requirement: OpenAI provider handles oversized audio by chunking

The `OpenAIWhisperProvider` SHALL compare the input audio file size against a configurable threshold `OPENAI_WHISPER_CHUNK_SIZE_MB` (default 24). When the file size exceeds the threshold, the provider SHALL split the audio into sequential time-based chunks, transcribe each chunk via the Whisper API, and merge the results into a single `TranscriptionResult`. When the file size is at or below the threshold, the provider SHALL upload the file in a single request as before.

#### Scenario: Small audio uses single request

- **WHEN** `OpenAIWhisperProvider.transcribe()` is called with an audio file whose size is at or below `OPENAI_WHISPER_CHUNK_SIZE_MB * 1024 * 1024` bytes
- **THEN** the provider SHALL issue exactly one `audio.transcriptions.create` call with the full file and SHALL return a `TranscriptionResult` with segments whose `start` and `end` values equal the API response values

#### Scenario: Oversized audio split and merged

- **WHEN** `OpenAIWhisperProvider.transcribe()` is called with an audio file whose size exceeds `OPENAI_WHISPER_CHUNK_SIZE_MB * 1024 * 1024` bytes
- **THEN** the provider SHALL split the audio into `ceil(file_size_bytes / threshold_bytes)` sequential chunks of equal duration, SHALL call `audio.transcriptions.create` once per chunk, and SHALL return a single `TranscriptionResult` whose `text` is the concatenation of each chunk's text separated by single spaces, whose `language` equals the first non-null language returned by any chunk, and whose `segments` are the union of all chunk segments with `start` and `end` offset by the cumulative duration of preceding chunks so the timeline is continuous with the original audio

#### Scenario: Chunk upload failure surfaces as exception

- **WHEN** any chunk's `audio.transcriptions.create` call raises an exception during oversized audio transcription
- **THEN** `OpenAIWhisperProvider.transcribe()` SHALL propagate the exception to the caller and SHALL NOT return a partial `TranscriptionResult`

#### Scenario: Temporary chunk files cleaned up

- **WHEN** `OpenAIWhisperProvider.transcribe()` finishes for an oversized audio file, whether it succeeded or raised an exception
- **THEN** all chunk files the provider wrote to disk SHALL be deleted before the method returns or re-raises

<!-- @trace
source: openai-audio-chunking
updated: 2026-04-22
code:
  - backend/app/api/health.py
  - backend/app/models/transcript_segment.py
  - backend/app/core/config.py
  - backend/app/api/transcripts.py
  - backend/alembic.ini
  - backend/app/workers/__init__.py
  - backend/alembic/versions/91e48beb1237_initial_schema.py
  - backend/app/main.py
  - backend/app/schemas/__init__.py
  - backend/app/services/rss_parser.py
  - backend/app/core/__init__.py
  - backend/app/workers/celery_app.py
  - .spectra/spectra.db
  - backend/app/services/transcription/openai_provider.py
  - backend/app/workers/dispatch.py
  - backend/Dockerfile
  - backend/app/services/__init__.py
  - backend/app/models/episode.py
  - backend/alembic/versions/a7b3c9d4e2f1_add_transcription_columns.py
  - backend/app/models/transcript.py
  - backend/app/services/transcription/base.py
  - backend/alembic/env.py
  - backend/app/schemas/sync.py
  - backend/alembic/README
  - backend/.dockerignore
  - backend/alembic/script.py.mako
  - backend/app/schemas/episode.py
  - backend/app/services/transcription/factory.py
  - backend/.env.example
  - backend/app/api/episodes.py
  - backend/requirements.txt
  - backend/app/workers/tasks.py
  - backend/app/__init__.py
  - backend/docker-compose.yml
  - backend/app/services/transcription/faster_whisper_provider.py
  - backend/app/models/__init__.py
  - backend/app/services/storage.py
  - backend/app/api/__init__.py
  - backend/app/api/shows.py
  - backend/app/schemas/show.py
  - backend/app/models/show.py
  - backend/app/schemas/transcript.py
  - backend/app/core/database.py
  - backend/app/services/transcription/__init__.py
-->