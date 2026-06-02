## MODIFIED Requirements

### Requirement: Pending candidate review section

The ASR correction admin tab SHALL present a section listing LLM-detected pending candidates (`source='llm'`, `status='pending'`) for review, showing each candidate's `wrong`, `correct`, and bound show. The `correct` value SHALL be presented in an editable field pre-filled with the detected value, so an admin can adjust it before approving; approving SHALL send the (possibly edited) `correct` to the approve endpoint. The section SHALL also provide a reject control. The section SHALL be bilingual (zh/en) and SHALL use the existing design tokens. After approve or reject, the list SHALL reflect the updated state.

#### Scenario: Candidate list loads with editable correct

- **WHEN** an admin opens the ASR correction tab with pending LLM candidates present
- **THEN** each candidate SHALL show its `correct` in an editable field plus approve and reject controls

#### Scenario: Approve with edited correct

- **WHEN** an admin edits a candidate's `correct` field and approves
- **THEN** the approved rule SHALL use the edited value and the candidate SHALL leave the pending list

#### Scenario: Reject removes candidate from pending list

- **WHEN** an admin rejects a pending candidate
- **THEN** the candidate SHALL no longer appear in the pending list
