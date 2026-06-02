## ADDED Requirements

### Requirement: Original transcript text preserved before correction

When transcription applies ASR corrections to a segment such that its text changes, the system SHALL preserve the pre-correction text so the correction is reversible. The original text SHALL be captured once: if the segment's `original_text` is null it SHALL be set to the text as it was before this correction; if it is already non-null it SHALL NOT be overwritten (the earliest ASR original is always retained). Likewise, when an episode's transcript is first corrected, if the transcript's `original_content` is null it SHALL be set to the pre-correction content.

#### Scenario: First correction snapshots original

- **GIVEN** a freshly transcribed segment whose text a correction changes and whose `original_text` is null
- **WHEN** the correction is applied during transcription
- **THEN** `original_text` SHALL hold the pre-correction text and `text` SHALL hold the corrected text

#### Scenario: Subsequent correction does not overwrite original

- **GIVEN** a segment whose `original_text` is already set
- **WHEN** another correction changes its text
- **THEN** `original_text` SHALL remain the earliest pre-correction text

### Requirement: Transcript content reflects corrections

After transcription applies corrections, the transcript's `content` (the full-episode text) SHALL reflect the same corrections as the segments, so the displayed transcript and the segments/search index stay consistent.

#### Scenario: Content corrected at transcription

- **WHEN** an episode is transcribed and corrections apply
- **THEN** `transcripts.content` SHALL contain the corrected text (not the raw ASR text)
