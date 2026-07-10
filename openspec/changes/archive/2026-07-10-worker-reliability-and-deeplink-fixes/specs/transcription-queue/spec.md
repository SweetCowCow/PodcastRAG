## ADDED Requirements

### Requirement: Consecutive lost-run counter terminates the revive loop

The `transcription_queue` table SHALL carry a `failure_count` integer column (NOT NULL, DEFAULT 0). Whenever the orphan-revert mechanism moves a `running` row back to `pending` (its Celery task is no longer alive), it SHALL increment that row's `failure_count` by 1. When the increment reaches `MAX_CONSECUTIVE_FAILURES` (constant, value 3), the row SHALL instead be set to `status='failed'` with an error message stating that automatic retries stopped after 3 consecutive lost runs. A manual retry from the admin queue UI SHALL reset `failure_count` to 0. A successful completion SHALL also reset `failure_count` to 0.

#### Scenario: Third consecutive lost run terminates the row

- **GIVEN** a queue row whose `failure_count` is 2
- **WHEN** orphan-revert detects its running task is lost again
- **THEN** the row SHALL become `status='failed'` (not `pending`)
- **AND** `error_message` SHALL mention that automatic retries stopped
- **AND** subsequent dispatcher polls SHALL NOT dispatch this episode

#### Scenario: Manual retry resets the counter

- **GIVEN** a row terminated with `failure_count` = 3
- **WHEN** an admin triggers retry from the queue UI
- **THEN** the row SHALL re-enter the queue with `failure_count` = 0

#### Scenario: Successful completion resets the counter

- **GIVEN** a row with `failure_count` = 2 that is dispatched again
- **WHEN** the task completes successfully
- **THEN** the row SHALL end `status='completed'` with `failure_count` = 0

### Requirement: Dispatcher never dispatches ASR for externally imported rows

When the dispatcher pops a `pending` queue row whose `whisper_model` starts with the `external:` prefix, it SHALL NOT send a `transcribe_episode` Celery task. It SHALL instead set the row to `status='failed'` with an error message stating the episode is externally imported and must be re-imported via the transcript-import endpoint. The transcript-import endpoint's existing revive path (failed/cancelled → running) SHALL remain the only way such a row returns to processing.

#### Scenario: External row popped by dispatcher is failed, not dispatched

- **GIVEN** a queue row with `whisper_model='external:faster-whisper-large-v3-turbo'` that has been reverted to `pending` (its import task was lost)
- **WHEN** the dispatcher polls and pops this row
- **THEN** no `transcribe_episode` Celery task SHALL be sent for this episode
- **AND** the row SHALL become `status='failed'` with an error message mentioning re-import

#### Scenario: Normal ASR row is unaffected

- **GIVEN** a pending queue row whose `whisper_model` is `large-v3`
- **WHEN** the dispatcher pops it
- **THEN** a `transcribe_episode` task SHALL be dispatched exactly as before
