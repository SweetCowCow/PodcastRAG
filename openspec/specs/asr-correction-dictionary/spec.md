# asr-correction-dictionary Specification

## Purpose

TBD - created by archiving change 'asr-correction-dictionary'. Update Purpose after archive.

## Requirements

### Requirement: ASR correction rule data model

The backend SHALL persist ASR correction rules in an `asr_correction_terms` table. Each rule SHALL have: `id` (uuid primary key), `wrong` (text, the ASR mis-transcription), `correct` (text, the intended text), `scope` (text, either `global` or `show`), `show_id` (uuid, nullable, required when scope is `show`), `enabled` (boolean, default true), `source` (text, either `manual` or `llm`, default `manual`), `status` (text, one of `pending`, `approved`, `rejected`, default `approved`), `note` (text, nullable), `created_by_user_id` (uuid, nullable), `created_at`, and `updated_at`. The table SHALL enforce a unique constraint on `(wrong, scope, show_id)`. Existing rows created before this change SHALL be treated as `source='manual'`, `status='approved'`.

#### Scenario: Manual rule defaults to approved

- **WHEN** a rule is created through the manual CRUD API without specifying source or status
- **THEN** it SHALL be stored with `source='manual'` and `status='approved'`

#### Scenario: LLM candidate stored pending and disabled

- **WHEN** an LLM-detected candidate is persisted
- **THEN** it SHALL be stored with `source='llm'`, `status='pending'`, and `enabled=false`

#### Scenario: Show-scoped rule requires show_id

- **WHEN** a rule is persisted with `scope='show'` and a null `show_id`
- **THEN** the system SHALL reject it with a validation error


<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: Literal whole-term matching

The correction service SHALL match each rule's `wrong` value as a literal full-string substring using plain string matching and SHALL NOT interpret it as a regular expression or wildcard pattern. A match SHALL replace every literal occurrence of `wrong` with `correct`.

#### Scenario: Literal occurrence replaced

- **WHEN** text contains the literal substring of a rule's `wrong`
- **THEN** every occurrence SHALL be replaced with `correct`

#### Scenario: Regex metacharacters treated literally

- **GIVEN** a rule `wrong='a.b', correct='X'`
- **WHEN** applied to the text `acb`
- **THEN** the text SHALL remain `acb` because the dot is matched literally, not as a wildcard

##### Example: literal replacement cases

| Rule (wrong→correct) | Input text | Output |
| -------------------- | ---------- | ------ |
| 咪有企→滅火器 | 今天聊咪有企的歌 | 今天聊滅火器的歌 |
| 世韻→世運 | 世韻會開幕 | 世運會開幕 |
| a.b→X | acb | acb |


<!-- @trace
source: asr-correction-dictionary
updated: 2026-06-01
code:
  - skills-lock.json
  - docs/roadmap.md
-->

---
### Requirement: Rule scope resolution by show

When resolving the rule set applicable to an episode of a given show, the correction service SHALL include only rules with `status='approved'` and `enabled=true`, comprising all such rules with `scope='global'` together with all such rules where `scope='show'` and `show_id` equals that show. Pending, rejected, or disabled rules SHALL NOT be included.

#### Scenario: Pending candidate excluded from resolution

- **GIVEN** an LLM candidate with `status='pending'`, `enabled=false` bound to show S
- **WHEN** the rule set for an episode of show S is resolved
- **THEN** the candidate SHALL NOT be included

#### Scenario: Approved enabled rules unioned

- **GIVEN** an approved enabled global rule G and an approved enabled show rule H bound to show S
- **WHEN** the rule set for an episode of show S is resolved
- **THEN** the set SHALL contain G and H


<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->

---
### Requirement: Backfill recomputes only affected chunks

A backfill operation SHALL update the `text` of every `transcript_segments` row that contains any applicable rule's `wrong` value, then SHALL recompute only the `transcript_chunks` rows whose `segment_ids` reference an updated segment. For each affected chunk the operation SHALL rebuild `text` from the updated segments and recompute `embedding`, `embedding_v2`, and `text_tsvector`. Chunks with no updated segment SHALL remain unchanged.

#### Scenario: Only affected chunks recomputed

- **GIVEN** a transcript where segment X in chunk C1 contains a rule's `wrong` and chunk C2 contains no matching segment
- **WHEN** backfill runs for the applicable rules
- **THEN** C1's `text`, `embedding`, `embedding_v2`, and `text_tsvector` SHALL be recomputed and C2 SHALL remain unchanged

#### Scenario: Corrected term becomes searchable

- **GIVEN** an existing transcript whose chunk contains the mis-transcription and a rule correcting it
- **WHEN** backfill completes
- **THEN** a keyword search for the corrected term SHALL match that chunk


<!-- @trace
source: asr-correction-dictionary
updated: 2026-06-01
code:
  - skills-lock.json
  - docs/roadmap.md
-->

---
### Requirement: Backfill runs as a resumable idempotent background task

Backfill SHALL run as a background task rather than a synchronous request, SHALL commit progress in batches, and SHALL be idempotent so that re-running it over an already-corrected chunk yields the same result. A failure recomputing one chunk SHALL be recorded and skipped without aborting the whole task, and the task SHALL report counts of affected segments, affected chunks, and the list of failed chunks.

#### Scenario: Single chunk failure isolated

- **GIVEN** a backfill over multiple chunks where one chunk's embedding recompute fails
- **WHEN** the task runs
- **THEN** the failing chunk SHALL be recorded and skipped and the remaining chunks SHALL still be recomputed

#### Scenario: Re-run is idempotent

- **WHEN** backfill runs twice over the same transcript with the same rule set
- **THEN** the second run SHALL produce the same corrected text and SHALL NOT double-apply replacements


<!-- @trace
source: asr-correction-dictionary
updated: 2026-06-01
code:
  - skills-lock.json
  - docs/roadmap.md
-->

---
### Requirement: Correction rule CRUD API

The backend SHALL expose admin-only endpoints to manage correction rules: list rules, create a rule, update a rule including toggling `enabled`, delete a rule, and trigger a backfill scoped by `scope`, `show_id`, or `term_id`. The backfill endpoint SHALL enqueue the background task and return a task identifier. Creating or updating a `scope='show'` rule without a `show_id` SHALL return HTTP 422.

#### Scenario: Create show rule without show_id rejected

- **WHEN** a POST creates a rule with `scope='show'` and no `show_id`
- **THEN** the API SHALL return HTTP 422

#### Scenario: Backfill enqueues task

- **WHEN** a POST to the backfill endpoint is made with a valid scope
- **THEN** the API SHALL enqueue the background task and return a task identifier

#### Scenario: Endpoints require admin

- **WHEN** a non-admin calls any correction rule endpoint
- **THEN** the API SHALL reject the request

<!-- @trace
source: asr-correction-dictionary
updated: 2026-06-01
code:
  - skills-lock.json
  - docs/roadmap.md
-->

---
### Requirement: Candidate review API

The backend SHALL expose admin-only endpoints to list pending candidates and to review a candidate by approving or rejecting it. Approving a candidate SHALL set `status='approved'` and `enabled=true`. Rejecting a candidate SHALL set `status='rejected'` and leave `enabled=false`. Listing SHALL support filtering by `source` and `status`.

#### Scenario: Approve candidate activates rule

- **GIVEN** a candidate with `status='pending'`, `enabled=false`
- **WHEN** an admin approves it
- **THEN** it SHALL have `status='approved'` and `enabled=true` and SHALL thereafter be included in rule resolution

#### Scenario: Reject candidate keeps it inactive

- **GIVEN** a candidate with `status='pending'`
- **WHEN** an admin rejects it
- **THEN** it SHALL have `status='rejected'` and `enabled=false` and SHALL NOT be included in rule resolution

#### Scenario: Review endpoints require admin

- **WHEN** a non-admin calls a candidate review endpoint
- **THEN** the API SHALL reject the request

<!-- @trace
source: asr-llm-homophone-postprocess
updated: 2026-06-02
code:
  - skills-lock.json
-->