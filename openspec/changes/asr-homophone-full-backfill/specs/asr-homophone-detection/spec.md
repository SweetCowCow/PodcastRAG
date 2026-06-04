## ADDED Requirements

### Requirement: Detection backfill over a show's existing episodes

The system SHALL provide a per-show entry point that runs homophone detection over every existing episode transcript of one show, reusing the established detection path (candidate-entity grounding, `detect_homophones`, `persist_candidates`). The backfill SHALL only produce pending candidates and SHALL NOT modify any transcript text. It SHALL run as a dedicated background job that does NOT use the transcription queue. A dry-run mode SHALL return a cost estimate (episode count, estimated input tokens, estimated USD) without invoking the LLM, writing candidates, or touching any transcript.

#### Scenario: Dry-run returns a cost estimate without side effects

- **WHEN** an admin requests detection over a show's existing episodes with dry_run=true
- **THEN** the system SHALL return the episode count, estimated input tokens, and estimated cost in USD, and SHALL NOT call the LLM, persist any candidate, or change any transcript

#### Scenario: Real run produces pending candidates only

- **WHEN** an admin runs detection over a show's existing episodes with dry_run=false
- **THEN** the system SHALL enqueue a background job that, per episode, detects homophone pairs and persists them as pending, disabled, show-scoped LLM candidates, and SHALL NOT modify any transcript text

#### Scenario: A single episode's detection failure does not abort the batch

- **WHEN** detection for one episode fails (LLM or parse error) during the backfill
- **THEN** that episode SHALL be counted as failed, a warning SHALL be logged, and the backfill SHALL continue with the remaining episodes (fail-open)

#### Scenario: Re-running detection does not create duplicate candidates

- **WHEN** detection backfill runs over a show whose episodes already produced candidates in a previous run
- **THEN** existing `(wrong, scope=show, show_id)` candidates SHALL be skipped without insert or status change, so no duplicate candidate is created
