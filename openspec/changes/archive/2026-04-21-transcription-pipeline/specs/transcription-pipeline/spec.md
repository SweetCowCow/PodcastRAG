## ADDED Requirements

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

### Requirement: Transcribe episode worker task

The backend SHALL define a Celery task `transcribe_episode(episode_id)` that sets transcript status to `processing`, ensures the audio file is stored in object storage, invokes the configured provider, persists segments, and sets the final status to `completed` or `failed`.

#### Scenario: Successful transcription

- **WHEN** the task is dispatched for an episode with a reachable `audio_url` and a working provider
- **THEN** the transcript SHALL end with `status="completed"`, `error_message=null`, `transcribed_at` set to the current UTC time, and `transcript_segments` SHALL contain one row per segment returned by the provider

#### Scenario: Audio download failure

- **WHEN** the task cannot download the audio from `audio_url` and no prior `audio_storage_key` exists
- **THEN** the transcript SHALL end with `status="failed"` and `error_message` SHALL describe the download failure

#### Scenario: Provider error

- **WHEN** the provider raises an exception during transcription
- **THEN** the transcript SHALL end with `status="failed"`, `error_message` SHALL contain the exception message (truncated to 2000 characters), and the Celery task SHALL not auto-retry

#### Scenario: Audio reused across transcriptions

- **WHEN** the task runs for an episode that already has a non-null `audio_storage_key`
- **THEN** the task SHALL download the audio from object storage and SHALL NOT fetch `audio_url` again
