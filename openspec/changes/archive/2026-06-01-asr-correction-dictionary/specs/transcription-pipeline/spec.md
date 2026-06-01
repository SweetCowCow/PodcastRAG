## ADDED Requirements

### Requirement: ASR correction applied before chunking

After obtaining the transcription result and before writing segments and building chunks, the transcription worker SHALL load the ASR correction rule set for the episode's show and SHALL apply it to each segment's text and to the full transcript content, so that both the displayed transcript and the search index are corrected at the source. If loading or applying corrections fails, the worker SHALL log a warning and continue the transcription without aborting (fail-open).

#### Scenario: New transcript corrected at source

- **GIVEN** an enabled correction rule applicable to the episode's show
- **WHEN** the episode is transcribed
- **THEN** the stored segment text, the transcript content, and the resulting chunks SHALL contain the corrected text

#### Scenario: Correction failure does not block transcription

- **WHEN** loading or applying correction rules raises an error during transcription
- **THEN** the worker SHALL log a warning and SHALL complete the transcription without the correction
