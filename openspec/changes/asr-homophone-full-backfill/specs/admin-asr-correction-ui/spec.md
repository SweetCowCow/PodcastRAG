## ADDED Requirements

### Requirement: Admin UI triggers detection over a show's existing episodes

The admin ASR correction tab SHALL let an admin trigger homophone detection over a selected show's existing episodes. The UI SHALL first present the dry-run cost estimate (episode count, estimated tokens, estimated USD) and SHALL require explicit confirmation before starting the real run. The tab SHALL remain bilingual (Traditional Chinese and English) and SHALL use the shared TOKEN design system.

#### Scenario: Cost estimate shown before real run

- **WHEN** an admin chooses to detect over a show's existing episodes
- **THEN** the UI SHALL display the dry-run cost estimate and SHALL start the real detection job only after the admin confirms

### Requirement: Admin UI shows backfill progress, failures, and cancellation

The admin tab SHALL display the progress of a running backfill job (detection or rule application) as a `current`/`total` indicator, SHALL surface the failed chunk ids, and SHALL provide a control to cancel the running job.

#### Scenario: Progress and cancel are visible for a running job

- **WHEN** a backfill job is running and the admin views the ASR correction tab
- **THEN** the UI SHALL show the `current`/`total` progress, any failed chunk ids, and a cancel control that stops the job

### Requirement: Admin UI offers batch restore and approve-and-apply

The admin tab SHALL provide a batch restore control that reverts the episodes touched by rule application back to their original ASR text. When approving a candidate, the tab SHALL offer an option to also apply the approved rule to existing episodes in the same action.

#### Scenario: Approve with apply-to-existing option

- **WHEN** an admin approves a candidate and selects the apply-to-existing option
- **THEN** the UI SHALL approve the candidate and start a rule-application job for that rule, surfacing the job's progress

#### Scenario: Batch restore control

- **WHEN** an admin triggers batch restore from the tab
- **THEN** the UI SHALL revert the affected episodes to their original ASR text and report the affected counts
