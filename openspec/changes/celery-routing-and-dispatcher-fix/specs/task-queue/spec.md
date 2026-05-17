## ADDED Requirements

### Requirement: Queue routing splits tasks across four named queues

The Celery application SHALL configure `task_routes` so that each task class is routed to one of four named queues based on its workload category:

- `transcribe` queue: `app.workers.tasks.transcribe_episode`
- `topic` queue: `app.workers.topic_task.classify_episode_topics`
- `summary` queue: `app.workers.summary_task.generate_episode_summary`
- `control` queue: cron_tick, quota_digest, eval_reminder, db_backup, tokenizer_reload, and any task without an explicit route

The `task_default_queue` SHALL be set to `control` so that tasks added in the future without an explicit `task_routes` entry are not silently dropped or sent to a queue that no worker is listening to.

#### Scenario: transcribe task routed to transcribe queue

- **WHEN** `transcribe_episode.delay(episode_id)` is called
- **THEN** the broker SHALL receive the task message on the queue named `transcribe`

#### Scenario: topic task routed to topic queue

- **WHEN** `classify_episode_topics.delay(episode_id)` is called
- **THEN** the broker SHALL receive the task message on the queue named `topic`

#### Scenario: unrouted task falls back to control queue

- **WHEN** a new task `app.workers.foo.bar` is registered with no entry in `task_routes` and `bar.delay()` is called
- **THEN** the broker SHALL receive the task message on the queue named `control`

---

### Requirement: Message priority orders task dispatch within and across queues

The Celery application SHALL set `task_queue_max_priority=10` and `task_default_priority=5`, and configure `broker_transport_options={"priority_steps": [0, 3, 6, 9]}` for the Redis broker. Each task SHALL declare a default priority value via its `apply_async`/`delay` configuration:

- `transcribe_episode`: priority `9` (highest)
- `classify_episode_topics`: priority `2`
- `generate_episode_summary`: priority `2`
- All other tasks: priority `5` (default)

When a worker process becomes idle, the Redis broker SHALL deliver the highest-priority pending message available across all subscribed queues before delivering any lower-priority message.

#### Scenario: high-priority transcribe preempts low-priority backfill

- **GIVEN** the worker has 6 prefork slots, 5 of which are currently running `classify_episode_topics` tasks (priority=2)
- **AND** 100 additional `classify_episode_topics` tasks are pending on the `topic` queue
- **AND** 1 `transcribe_episode` task (priority=9) is pending on the `transcribe` queue
- **WHEN** the next prefork slot becomes idle (current task completes)
- **THEN** the worker SHALL pick up the `transcribe_episode` task before any of the 100 pending `topic` tasks

##### Example: priority pop order

| Pending messages on broker | Next idle slot picks |
| -------------------------- | -------------------- |
| 50× topic (p=2) | 1× topic (p=2) |
| 50× topic (p=2), 1× transcribe (p=9) | 1× transcribe (p=9) |
| 1× control cron_tick (p=5), 50× topic (p=2) | 1× cron_tick (p=5) |
| 1× transcribe (p=9), 1× cron_tick (p=5), 1× topic (p=2) | 1× transcribe (p=9), then cron_tick, then topic |

#### Scenario: tasks within the same priority level use queue FIFO order

- **GIVEN** 10 `classify_episode_topics` tasks (priority=2) enqueued in order T1...T10
- **WHEN** a worker slot becomes idle
- **THEN** the worker SHALL pick up T1 before T2 (FIFO within the same priority bucket)

---

### Requirement: Worker subscribes to all four named queues

The Celery worker process SHALL be started with `--queues=transcribe,topic,summary,control` so that it consumes from all four routed queues. The Zeabur `worker` service `START_COMMAND` SHALL include this flag. The worker SHALL not be configured to listen exclusively to a subset (no per-queue worker split is introduced).

#### Scenario: Worker accepts task from any of the four queues

- **GIVEN** the worker is running with `--queues=transcribe,topic,summary,control`
- **WHEN** any task is dispatched to any one of the four queues
- **THEN** the worker SHALL receive and execute the task within 5 seconds of broker delivery (subject to concurrency slot availability)

#### Scenario: Worker without --queues flag rejects new queues

- **GIVEN** the worker `START_COMMAND` does not include `--queues`
- **WHEN** a `classify_episode_topics` task is dispatched to the `topic` queue
- **THEN** the worker SHALL NOT receive the message
- **AND** the message SHALL accumulate on the `topic` queue indefinitely

---

### Requirement: Existing tests for queue behaviour SHALL pass without regression

All existing tests under `backend/tests/` that exercise Celery task dispatch, throttling, and worker lifecycle SHALL continue to pass after the routing and priority configuration is added. The change SHALL NOT break the `transcribe_episode` task's interaction with the global concurrency semaphore, per-show lock, or graceful shutdown handler.

#### Scenario: Throttle semaphore continues to function

- **GIVEN** `MAX_CONCURRENT_TRANSCRIPTIONS=1` and one `transcribe_episode` task is currently active
- **WHEN** a second `transcribe_episode` task is enqueued (now to the `transcribe` queue with priority=9)
- **THEN** the second task SHALL still self-requeue via the existing `transcribe:global:active_count` check
- **AND** the per-show Redis lock SHALL still be honored
