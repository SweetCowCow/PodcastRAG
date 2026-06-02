## ADDED Requirements

### Requirement: Pending candidate review section

The ASR correction admin tab SHALL present a section listing LLM-detected pending candidates (`source='llm'`, `status='pending'`) for review, showing each candidate's `wrong`, `correct`, and bound show, with controls to approve or reject each candidate. The section SHALL be bilingual (zh/en) and SHALL use the existing design tokens. After approve or reject, the list SHALL reflect the updated state.

#### Scenario: Candidate list loads and reviews

- **WHEN** an admin opens the ASR correction tab with pending LLM candidates present
- **THEN** the candidates SHALL be listed with approve and reject controls

#### Scenario: Approve removes candidate from pending list

- **WHEN** an admin approves a pending candidate
- **THEN** the candidate SHALL no longer appear in the pending list and SHALL appear as an active rule
