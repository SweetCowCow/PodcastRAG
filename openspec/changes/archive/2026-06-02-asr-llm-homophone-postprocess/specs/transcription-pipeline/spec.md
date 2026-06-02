## ADDED Requirements

### Requirement: LLM homophone detection precedes dictionary correction

During transcription, after the Whisper result is obtained and before segments are persisted and chunked, the worker SHALL run LLM homophone detection (the first layer) and apply its returned pairs to the segment text, then SHALL apply the approved dictionary rules (the second layer). Both layers SHALL complete before `build_chunks` and embedding so that the displayed transcript and the search index reflect both corrections. The detection layer SHALL be fail-open and SHALL NOT block transcription on failure.

#### Scenario: Both layers applied before chunking

- **GIVEN** an episode whose Whisper output contains an unknown homophone the LLM detects and a known typo covered by an approved dictionary rule
- **WHEN** the episode is transcribed
- **THEN** the persisted segments, transcript content, and chunks SHALL reflect both the LLM-detected correction and the dictionary correction

#### Scenario: Detection failure falls back to dictionary only

- **WHEN** the LLM detection layer fails for an episode
- **THEN** transcription SHALL still complete applying only the approved dictionary rules
