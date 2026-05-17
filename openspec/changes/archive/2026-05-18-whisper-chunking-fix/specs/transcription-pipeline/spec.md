## ADDED Requirements

### Requirement: OpenAI Whisper provider rejects oversized uploads with explicit error

Before issuing any HTTP request to `audio.transcriptions.create`, the OpenAI Whisper provider SHALL verify that the file (or chunk) about to be uploaded is at most 25 MiB (25 × 1024 × 1024 = 26,214,400 bytes — the OpenAI documented hard limit). If the file size exceeds this limit, the provider SHALL raise a typed exception `OversizedAudioError` with the message containing the actual file size and the configured `openai_whisper_chunk_size_mb` value, and SHALL NOT make the HTTP call.

This guard SHALL apply to BOTH the single-file upload path AND every chunk produced by `_split_audio`. The chunking code path's intent is to keep each chunk under the configured threshold, but the explicit guard catches edge cases (ffmpeg keyframe alignment overshoot, multipart overhead pushing close to limit) before they consume retry budget against an irrecoverable upstream rejection.

#### Scenario: File at exactly 25 MiB allowed

- **GIVEN** an audio file of size 26,214,400 bytes
- **WHEN** the provider attempts to upload it
- **THEN** the upload SHALL proceed (size <= limit)

#### Scenario: File above 25 MiB raises OversizedAudioError before upload

- **GIVEN** an audio file of size 26,214,401 bytes (1 byte over limit)
- **WHEN** the provider's `_transcribe_sync` runs
- **THEN** an `OversizedAudioError` SHALL be raised
- **AND** no `audio.transcriptions.create` HTTP call SHALL be made
- **AND** the exception message SHALL contain the file size in bytes and the current `openai_whisper_chunk_size_mb` value

#### Scenario: Chunk produced by _split_audio above 25 MiB raises OversizedAudioError

- **GIVEN** `openai_whisper_chunk_size_mb=24` and `_split_audio` produces a chunk that ended up at 25.1 MiB due to ffmpeg keyframe overshoot
- **WHEN** the provider tries to upload that chunk
- **THEN** an `OversizedAudioError` SHALL be raised for that chunk before the HTTP call
- **AND** the error message SHALL include the chunk index and size

---

### Requirement: Audio path resolution ensures local file before chunking

Before `_transcribe_sync` reads `os.path.getsize(audio_path)` to decide chunking, the worker SHALL ensure `audio_path` refers to a local file (not a presigned URL or remote URI) by:

1. Calling `os.path.exists(audio_path)` and confirming True.
2. Verifying `audio_path` does not start with `http://` or `https://` or `s3://`.
3. Logging the resolved path + size at INFO level so prod can audit any subsequent chunking decision.

If the path fails the local-file check, the provider SHALL raise a typed exception `RemoteAudioPathError` indicating the audio_path was not downloaded to local disk before transcription was attempted. The worker layer (`tasks.py`) SHALL catch this and download the file to a temp path before retrying.

#### Scenario: Local temp file proceeds normally

- **GIVEN** `audio_path = /tmp/podcast_abc.mp3` exists and `getsize` returns 26,400,000
- **WHEN** `_transcribe_sync` runs
- **THEN** the provider SHALL log `audio_path=/tmp/... size=26400000 chunk_size_bytes=23068672`
- **AND** SHALL proceed to chunking branch (size > chunk threshold)

#### Scenario: Remote URL raises RemoteAudioPathError

- **GIVEN** `audio_path = https://r2.example.com/audio/abc.mp3?signature=...`
- **WHEN** `_transcribe_sync` runs
- **THEN** a `RemoteAudioPathError` SHALL be raised before any further processing
- **AND** the worker SHALL catch it and download to local temp before retrying

---

### Requirement: Chunking decisions are observable in worker logs

Each invocation of `_transcribe_sync` SHALL emit a structured log line at INFO level containing: episode_id (if available via task context), audio_path basename, file size in bytes, configured `chunk_size_bytes`, decision taken (`single` or `chunked` and chunk count). This log SHALL be present even on success paths so prod operators can audit the chunking behaviour without enabling debug-level logging globally.

#### Scenario: Single-file path emits decision log

- **GIVEN** a 22 MB file processed without chunking
- **WHEN** `_transcribe_sync` completes
- **THEN** worker logs SHALL contain a line like `transcription: ep=<id> file=abc.mp3 size=22500000 chunk_threshold=23068672 decision=single`

#### Scenario: Chunked path emits decision log with chunk count

- **GIVEN** a 50 MB file split into 3 chunks
- **WHEN** `_transcribe_sync` completes
- **THEN** worker logs SHALL contain a line like `transcription: ep=<id> file=abc.mp3 size=52000000 chunk_threshold=23068672 decision=chunked chunks=3`
