## ADDED Requirements

### Requirement: Shared post-ASR persistence pipeline

The worker module SHALL expose a single shared persistence function that consumes a `TranscriptionResult` and performs the post-ASR pipeline (cancellation check, segment/chunk delete-then-write, LLM homophone detection with fail-open, ASR correction application, chunk building, dual embedding write, transcript content recomputation, and queue completion with downstream chaining). Both the provider transcription path (`transcribe_episode`) and the external import path (`import_external_transcript`) SHALL call this function, and the provider path's observable behavior SHALL remain unchanged by the extraction.

#### Scenario: Provider path behavior preserved

- **WHEN** `transcribe_episode` runs after the extraction refactor
- **THEN** all existing transcription-pipeline scenarios (successful transcription, provider error, embedding failure, re-transcription replacement, cancellation) SHALL pass unchanged against the refactored code

#### Scenario: Single pipeline for both entry paths

- **WHEN** the same `TranscriptionResult` content is persisted via the provider path and via the import path for equivalent episodes
- **THEN** both paths SHALL produce the same artifact shape: identical segment rows, ASR-corrected text, chunk construction, embedding columns written, and summary/topic chain-enqueue behavior
