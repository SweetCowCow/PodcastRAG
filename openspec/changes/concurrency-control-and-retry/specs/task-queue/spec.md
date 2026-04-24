## ADDED Requirements

### Requirement: Global concurrency semaphore bounds active transcriptions

The Celery `transcribe_episode` task SHALL enforce a cross-worker concurrency limit using a Redis-backed semaphore. The maximum number of simultaneously active transcriptions SHALL be configured by the `MAX_CONCURRENT_TRANSCRIPTIONS` environment variable, defaulting to `1`. When a task starts, it SHALL attempt to acquire a global slot by incrementing the Redis counter `transcribe:global:active_count`; if the incremented value exceeds the configured maximum, the task SHALL immediately decrement the counter back and requeue itself via `self.retry(countdown=15, max_retries=None)`. Successful or permanently failed tasks SHALL always decrement the counter in a `finally` block.

#### Scenario: Task runs when slot is available

- **WHEN** `MAX_CONCURRENT_TRANSCRIPTIONS=2` and 1 task is currently active
- **THEN** a newly-started task SHALL successfully acquire a slot and proceed with transcription

#### Scenario: Task requeues when limit reached

- **WHEN** `MAX_CONCURRENT_TRANSCRIPTIONS=1` and 1 task is currently active
- **THEN** a second task SHALL not proceed with transcription, SHALL decrement the counter back, and SHALL be requeued with a 15-second countdown

#### Scenario: Slot released on successful completion

- **WHEN** a task finishes transcription successfully
- **THEN** the counter `transcribe:global:active_count` SHALL be decremented by 1 before the task returns

#### Scenario: Slot released on permanent failure

- **WHEN** a task writes `transcript.status='failed'` due to a permanent error and returns
- **THEN** the counter `transcribe:global:active_count` SHALL still be decremented by 1

### Requirement: Per-show exclusivity lock

The Celery `transcribe_episode` task SHALL acquire a per-show Redis lock at key `transcribe:show:{show_id}:lock` using `SET NX EX 1800` (30-minute TTL) before beginning transcription. If the lock is already held, the task SHALL release its global slot and requeue itself via `self.retry(countdown=60, max_retries=None)`. On task completion (success or permanent failure), the task SHALL delete the lock.

#### Scenario: Task proceeds when show is not locked

- **WHEN** a task starts for show A and no `transcribe:show:A:lock` key exists
- **THEN** the task SHALL set the lock with 30-minute TTL and proceed

#### Scenario: Task requeues when show is already locked

- **WHEN** a task starts for show A and a second task for the same show A is already running
- **THEN** the second task SHALL fail to acquire the lock, release its global slot, and requeue with a 60-second countdown

#### Scenario: Lock auto-expires after TTL

- **WHEN** a worker holding `transcribe:show:A:lock` crashes without releasing
- **THEN** the lock SHALL automatically expire after 30 minutes, allowing future tasks for show A to proceed

#### Scenario: Different shows run in parallel under the global limit

- **WHEN** `MAX_CONCURRENT_TRANSCRIPTIONS=2` and tasks for show A and show B start simultaneously
- **THEN** both tasks SHALL acquire their per-show locks independently and run in parallel

### Requirement: Global slot key has a TTL safety net

When the task successfully acquires a global semaphore slot, it SHALL also `SET transcribe:global:slot:{task_id} 1 EX 7200` (2-hour TTL) as a side record of the slot holder. On release, the task SHALL delete both the side record and decrement the counter. The side record's TTL protects against permanent counter drift if the worker crashes between increment and finally-decrement.

#### Scenario: Side record created on acquire

- **WHEN** a task acquires a global slot
- **THEN** Redis SHALL contain a key `transcribe:global:slot:{task_id}` with a value and a TTL of at most 7200 seconds

#### Scenario: Side record deleted on release

- **WHEN** a task releases its global slot
- **THEN** the key `transcribe:global:slot:{task_id}` SHALL be deleted from Redis
