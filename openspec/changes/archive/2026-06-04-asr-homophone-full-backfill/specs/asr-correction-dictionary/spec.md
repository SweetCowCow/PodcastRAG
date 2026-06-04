## ADDED Requirements

### Requirement: Backfill jobs report progress and are cancellable

Both background backfill jobs — detection over existing episodes and rule application over existing transcripts — SHALL report progress as a unit count (`current`, `total`), a phase label, and an accumulated list of failed chunk ids, queryable by task id. The system SHALL expose a status query that maps every job state (pending, in-progress, success, failure, cancelled, unknown) onto a fixed response shape with a human-readable message, rather than returning the raw task-runner state. The system SHALL allow cancelling a running job by task id; cancellation SHALL stop further processing but SHALL NOT roll back work already committed.

#### Scenario: Status query maps an in-progress job to a fixed shape

- **WHEN** an admin queries the status of a running backfill job
- **THEN** the system SHALL return `current`, `total`, a phase label, the failed chunk ids so far, and a human-readable message

#### Scenario: Cancellation stops the job without rollback

- **WHEN** an admin cancels a running backfill job
- **THEN** the system SHALL stop further processing, SHALL leave already-committed episodes or transcripts unchanged, and SHALL report a cancelled state with a message indicating how many units were processed

#### Scenario: Status query for an unknown task id does not error

- **WHEN** an admin queries the status of a task id that does not exist or whose result has expired
- **THEN** the system SHALL return an unknown state with an explanatory message and SHALL NOT raise a server error

### Requirement: Batch restore of episodes touched by rule application

The system SHALL provide a batch restore that reverts the episodes affected by rule application back to their original ASR text, reusing the per-episode snapshot-and-restore mechanism. Each restored episode SHALL revert its corrected segments and content from their snapshots and recompute affected chunks.

#### Scenario: Batch restore reverts affected episodes

- **WHEN** an admin triggers a batch restore for a rule-application scope
- **THEN** the system SHALL revert each affected episode's segments and content from their snapshots, recompute affected chunks, and report the affected transcript, segment, and chunk counts plus any failed chunk ids

### Requirement: Approving a candidate can apply it to existing episodes

When approving a correction candidate, the system SHALL accept an optional flag to also apply the approved rule to existing episodes. When the flag is set, the system SHALL enqueue a rule-application background job scoped to that rule's id after approval succeeds and SHALL return its task id. When the flag is absent or false, approval SHALL only set the rule approved and enabled, with no rule-application job enqueued.

#### Scenario: Approve-and-apply enqueues a scoped application job

- **WHEN** an admin approves a candidate with the apply-to-existing flag set
- **THEN** the system SHALL set the rule approved and enabled, enqueue a rule-application job scoped to that rule's id, and return the job's task id

#### Scenario: Approve without the flag does not enqueue a job

- **WHEN** an admin approves a candidate without the apply-to-existing flag
- **THEN** the system SHALL set the rule approved and enabled and SHALL NOT enqueue any rule-application job
