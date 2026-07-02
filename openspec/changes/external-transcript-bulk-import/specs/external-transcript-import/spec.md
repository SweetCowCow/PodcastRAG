## ADDED Requirements

### Requirement: Admin transcript import endpoint

The backend SHALL expose `POST /admin/episodes/{episode_id}/transcript-import` (admin-only) accepting a JSON body `{model: string, language: string|null, text: string, segments: [{start: number, end: number, text: string}]}` that validates the payload and enqueues an import task, returning HTTP 202 with the Celery task id. The endpoint SHALL NOT write transcript artifacts synchronously.

#### Scenario: Valid payload accepted

- **WHEN** an admin posts a payload with non-empty `text`, at least one segment, and every segment having `0 <= start <= end` with non-empty segment text
- **THEN** the endpoint SHALL respond 202 with `{task_id, episode_id}` and enqueue `import_external_transcript` on the control queue

#### Scenario: Invalid payload rejected

- **WHEN** the payload has empty `segments`, a segment with `start > end`, a negative `start`, or empty `text`
- **THEN** the endpoint SHALL respond 422 and SHALL NOT enqueue any task

#### Scenario: Unknown episode rejected

- **WHEN** `episode_id` does not exist
- **THEN** the endpoint SHALL respond 404

#### Scenario: In-flight ASR transcription blocks import

- **WHEN** the episode has a `transcription_queue` row in `pending` or `running` status
- **THEN** the endpoint SHALL respond 409 and SHALL NOT enqueue any task

#### Scenario: Non-admin rejected

- **WHEN** the caller is not an authenticated admin
- **THEN** the endpoint SHALL respond 401 or 403 per the existing admin auth contract

### Requirement: External transcript import task

The backend SHALL define a Celery task `import_external_transcript(episode_id, payload)` that converts the payload into a `TranscriptionResult` and persists it through the same shared post-ASR persistence pipeline used by `transcribe_episode`, producing identical downstream artifacts (ASR corrections applied, segments, chunks, dual embeddings, transcript content) and chaining the summary and topic tasks on completion.

#### Scenario: Successful import

- **WHEN** the task runs for an episode with a valid payload
- **THEN** the transcript SHALL end with `status="completed"`, `transcript_segments` SHALL contain one row per payload segment, `transcript_chunks` SHALL be built with non-null embeddings, ASR correction dictionary rules SHALL be applied identically to the provider path, and the summary and topic tasks SHALL be chain-enqueued

#### Scenario: Re-import replaces artifacts

- **WHEN** the task runs for an episode that already has transcript segments and chunks from a prior import or transcription
- **THEN** existing segments and chunks SHALL be deleted and rebuilt from the new payload (idempotent overwrite), matching the existing re-transcription behavior

#### Scenario: Downstream failure marks transcript failed

- **WHEN** the embeddings API raises during chunk building
- **THEN** the transcript SHALL end with `status="failed"` with the error message recorded, and no partial `transcript_chunks` rows SHALL be left behind

### Requirement: Import queue row provenance

The import task SHALL ensure a `transcription_queue` row exists for the episode and ends in `completed` status with `whisper_model` set to an `external:` prefixed model label (e.g., `external:faster-whisper-large-v3-turbo`), so that scheduler enqueue logic and the admin queue UI treat imported episodes as already transcribed.

#### Scenario: Queue row created on import

- **WHEN** the import task runs for an episode with no `transcription_queue` row
- **THEN** a row SHALL be created and end in `completed` status with the `external:` prefixed model label

#### Scenario: Failed queue row revived on import

- **WHEN** the import task runs for an episode whose queue row is in `failed` or `cancelled` status
- **THEN** the existing row SHALL be reused and end in `completed` status with the `external:` prefixed model label

#### Scenario: Scheduler skips imported episodes

- **WHEN** a show schedule is enabled after historical episodes were imported
- **THEN** the cron-tick enqueue pass SHALL NOT enqueue any imported episode (their `completed` queue rows exclude them), and only episodes without completed/running/pending rows SHALL be eligible
