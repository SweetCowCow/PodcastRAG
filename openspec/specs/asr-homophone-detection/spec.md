# asr-homophone-detection Specification

## Purpose

TBD - created by archiving change 'asr-llm-homophone-postprocess'. Update Purpose after archive.

## Requirements

### Requirement: Detection is grounded on a per-show candidate-entity list (RAGEC)

The detection SHALL be grounded on a per-show candidate-entity list — the union of the show's distinct guest names, the correct-forms of its approved correction rules, and any supplied host names — and SHALL ask the LLM to map ASR mis-hearings onto that list rather than freely hunting for arbitrary typos. The system SHALL discard any returned pair whose `correct` is not in the candidate list or whose `wrong` does not appear in the transcript. When the candidate list is empty, detection SHALL skip the LLM call and return an empty list.

#### Scenario: Off-list correction is dropped

- **WHEN** the LLM returns a pair whose `correct` is not in the candidate-entity list
- **THEN** that pair SHALL be dropped from the result

#### Scenario: Empty candidate list skips detection

- **WHEN** a show has no candidate entities (no guests, no approved rules, no hosts)
- **THEN** detection SHALL return an empty list without invoking the LLM


<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: LLM homophone detection produces word-level pairs

After transcription produces segment text and before segments are persisted, the system SHALL invoke an LLM to detect homophone mis-transcriptions across the full episode transcript and SHALL return a list of word-level correction pairs `{wrong, correct}`. The detection SHALL NOT return rewritten full text, sentence restructuring, or tone edits; each pair's `wrong` and `correct` SHALL be terms suitable for literal substring replacement.

#### Scenario: Detection returns word-level pairs

- **WHEN** the LLM detection runs over an episode transcript containing a homophone mis-transcription
- **THEN** it SHALL return one or more `{wrong, correct}` pairs and SHALL NOT return rewritten full transcript text

#### Scenario: No confident detection returns empty

- **WHEN** the LLM finds no confident homophone mis-transcription
- **THEN** it SHALL return an empty pair list and transcription SHALL proceed unchanged


<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: Detected pairs applied to the current episode immediately

The detected pairs SHALL be applied to the current episode's segment text using the same literal whole-term replacement as the dictionary correction, before chunking and embedding, without depending on any persisted-rule approval state.

#### Scenario: Current episode corrected regardless of approval

- **GIVEN** the LLM returns a pair `{wrong, correct}` for the current episode
- **WHEN** the episode is transcribed
- **THEN** the current episode's segment text SHALL have every literal occurrence of `wrong` replaced with `correct` even though no rule for that pair has been approved


<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: Detected pairs persisted as pending candidates

Each detected pair SHALL be persisted into the correction rule store as a candidate with `source='llm'`, `status='pending'`, `enabled=false`, and `scope='show'` bound to the episode's show. A candidate whose `(wrong, scope, show_id)` already matches an existing rule of any status SHALL be skipped without insertion or status change.

#### Scenario: New detection persisted as pending candidate

- **WHEN** the LLM detects a pair not present in the rule store for the show
- **THEN** a candidate SHALL be inserted with `source='llm'`, `status='pending'`, `enabled=false`, `scope='show'`

#### Scenario: Duplicate detection skipped

- **GIVEN** a rule with the same `(wrong, scope, show_id)` already exists with any status
- **WHEN** the LLM detects the same pair again
- **THEN** no new candidate SHALL be inserted and the existing rule's status SHALL be unchanged


<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: Detection is fail-open

If the LLM call or its response parsing fails, the system SHALL log a warning, treat the detection result as an empty pair list, and SHALL complete transcription using only the approved dictionary rules. Detection failure SHALL NOT abort transcription.

#### Scenario: Detection failure does not block transcription

- **WHEN** the LLM call raises an error during transcription
- **THEN** the warning SHALL be logged and transcription SHALL still complete with dictionary-only correction


<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: Detection uses centralized AI step configuration

The LLM detection SHALL resolve its model and prompt from a centralized AI step named `asr_homophone`, consistent with other AI steps. Response parsing SHALL be tolerant of provider formatting variation so that swapping the configured model does not silently yield zero pairs: it SHALL accept a JSON payload wrapped in a markdown code block, a bare JSON array, an object wrapping the array under a key such as `pairs`/`corrections`, and a response with surrounding non-JSON text by extracting the first JSON array or object. Entries with case- or whitespace-variant `wrong`/`correct` keys SHALL be accepted. When parsing fails despite tolerance, detection SHALL fail open and return an empty list.

#### Scenario: Step config resolved

- **WHEN** detection runs
- **THEN** it SHALL use the model and prompt configured for the `asr_homophone` step

#### Scenario: Object-wrapped payload parsed

- **WHEN** the LLM returns an object wrapping the pair list under a `pairs` key (with or without a surrounding code block)
- **THEN** the pairs SHALL be parsed rather than treated as empty

#### Scenario: Payload with surrounding prose parsed

- **WHEN** the LLM returns a JSON array preceded or followed by explanatory text
- **THEN** the embedded JSON array SHALL be extracted and parsed


<!-- @trace
source: asr-correction-ux-and-aihub-json
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: Detection cost dry-run estimation

The system SHALL provide a dry-run estimation that, for a given set of pilot episodes, reports the estimated token usage and cost of running detection without invoking the LLM correction for real.

#### Scenario: Dry-run reports estimate without running

- **WHEN** a dry-run estimation is requested for a set of episodes
- **THEN** the system SHALL return estimated token and cost figures and SHALL NOT persist candidates or modify transcripts

<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
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

<!-- @trace
source: asr-homophone-full-backfill
updated: 2026-06-04
code:
  - skills-lock.json
-->