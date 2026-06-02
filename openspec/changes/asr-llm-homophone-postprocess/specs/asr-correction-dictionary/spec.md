## MODIFIED Requirements

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

## ADDED Requirements

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
