## ADDED Requirements

### Requirement: Detection is grounded on a per-show candidate-entity list (RAGEC)

The detection SHALL be grounded on a per-show candidate-entity list — the union of the show's distinct guest names, the correct-forms of its approved correction rules, and any supplied host names — and SHALL ask the LLM to map ASR mis-hearings onto that list rather than freely hunting for arbitrary typos. The system SHALL discard any returned pair whose `correct` is not in the candidate list or whose `wrong` does not appear in the transcript. When the candidate list is empty, detection SHALL skip the LLM call and return an empty list.

#### Scenario: Off-list correction is dropped

- **WHEN** the LLM returns a pair whose `correct` is not in the candidate-entity list
- **THEN** that pair SHALL be dropped from the result

#### Scenario: Empty candidate list skips detection

- **WHEN** a show has no candidate entities (no guests, no approved rules, no hosts)
- **THEN** detection SHALL return an empty list without invoking the LLM

### Requirement: LLM homophone detection produces word-level pairs

After transcription produces segment text and before segments are persisted, the system SHALL invoke an LLM to detect homophone mis-transcriptions across the full episode transcript and SHALL return a list of word-level correction pairs `{wrong, correct}`. The detection SHALL NOT return rewritten full text, sentence restructuring, or tone edits; each pair's `wrong` and `correct` SHALL be terms suitable for literal substring replacement.

#### Scenario: Detection returns word-level pairs

- **WHEN** the LLM detection runs over an episode transcript containing a homophone mis-transcription
- **THEN** it SHALL return one or more `{wrong, correct}` pairs and SHALL NOT return rewritten full transcript text

#### Scenario: No confident detection returns empty

- **WHEN** the LLM finds no confident homophone mis-transcription
- **THEN** it SHALL return an empty pair list and transcription SHALL proceed unchanged

### Requirement: Detected pairs applied to the current episode immediately

The detected pairs SHALL be applied to the current episode's segment text using the same literal whole-term replacement as the dictionary correction, before chunking and embedding, without depending on any persisted-rule approval state.

#### Scenario: Current episode corrected regardless of approval

- **GIVEN** the LLM returns a pair `{wrong, correct}` for the current episode
- **WHEN** the episode is transcribed
- **THEN** the current episode's segment text SHALL have every literal occurrence of `wrong` replaced with `correct` even though no rule for that pair has been approved

### Requirement: Detected pairs persisted as pending candidates

Each detected pair SHALL be persisted into the correction rule store as a candidate with `source='llm'`, `status='pending'`, `enabled=false`, and `scope='show'` bound to the episode's show. A candidate whose `(wrong, scope, show_id)` already matches an existing rule of any status SHALL be skipped without insertion or status change.

#### Scenario: New detection persisted as pending candidate

- **WHEN** the LLM detects a pair not present in the rule store for the show
- **THEN** a candidate SHALL be inserted with `source='llm'`, `status='pending'`, `enabled=false`, `scope='show'`

#### Scenario: Duplicate detection skipped

- **GIVEN** a rule with the same `(wrong, scope, show_id)` already exists with any status
- **WHEN** the LLM detects the same pair again
- **THEN** no new candidate SHALL be inserted and the existing rule's status SHALL be unchanged

### Requirement: Detection is fail-open

If the LLM call or its response parsing fails, the system SHALL log a warning, treat the detection result as an empty pair list, and SHALL complete transcription using only the approved dictionary rules. Detection failure SHALL NOT abort transcription.

#### Scenario: Detection failure does not block transcription

- **WHEN** the LLM call raises an error during transcription
- **THEN** the warning SHALL be logged and transcription SHALL still complete with dictionary-only correction

### Requirement: Detection uses centralized AI step configuration

The LLM detection SHALL resolve its model and prompt from a centralized AI step named `asr_homophone`, consistent with other AI steps. Response parsing SHALL tolerate a JSON payload wrapped in a markdown code block.

#### Scenario: Step config resolved

- **WHEN** detection runs
- **THEN** it SHALL use the model and prompt configured for the `asr_homophone` step

### Requirement: Detection cost dry-run estimation

The system SHALL provide a dry-run estimation that, for a given set of pilot episodes, reports the estimated token usage and cost of running detection without invoking the LLM correction for real.

#### Scenario: Dry-run reports estimate without running

- **WHEN** a dry-run estimation is requested for a set of episodes
- **THEN** the system SHALL return estimated token and cost figures and SHALL NOT persist candidates or modify transcripts
