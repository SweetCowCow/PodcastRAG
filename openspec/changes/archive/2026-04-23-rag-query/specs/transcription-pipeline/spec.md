## MODIFIED Requirements

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
