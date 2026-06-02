## MODIFIED Requirements

### Requirement: Candidate review API

The backend SHALL expose admin-only endpoints to list pending candidates and to review a candidate by approving or rejecting it. Approving a candidate SHALL set `status='approved'` and `enabled=true`; the approve request MAY include an optional `correct` value, and when present the system SHALL overwrite the rule's `correct` with that value before approving (an admin may fix a near-miss correction at approval time). When `correct` is omitted, the existing value SHALL be kept. The approve operation SHALL NOT change `wrong`, `scope`, or `show_id`. Rejecting a candidate SHALL set `status='rejected'` and leave `enabled=false`. Listing SHALL support filtering by `source` and `status`.

#### Scenario: Approve candidate activates rule

- **GIVEN** a candidate with `status='pending'`, `enabled=false`
- **WHEN** an admin approves it without an override
- **THEN** it SHALL have `status='approved'` and `enabled=true` and SHALL thereafter be included in rule resolution

#### Scenario: Approve with corrected text

- **GIVEN** a candidate `{wrong, correct}` with `status='pending'`
- **WHEN** an admin approves it with an override `correct` value
- **THEN** the rule's `correct` SHALL be the override value and `status='approved'`, `enabled=true`

#### Scenario: Reject candidate keeps it inactive

- **GIVEN** a candidate with `status='pending'`
- **WHEN** an admin rejects it
- **THEN** it SHALL have `status='rejected'` and `enabled=false` and SHALL NOT be included in rule resolution

#### Scenario: Review endpoints require admin

- **WHEN** a non-admin calls a candidate review endpoint
- **THEN** the API SHALL reject the request
